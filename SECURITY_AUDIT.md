# AutoDeskAI security audit — Phase 0

Scope: repository at commit `1c2138e` on `security-hardening`. This is a source audit, not a production penetration test. No production database, account, or secret was accessed. Statuses below describe the baseline before hardening. Line numbers refer to this baseline and will move as fixes land.

## Trust boundaries and existing controls

Employee and administrator browsers call FastAPI through Vercel's `/api` rewrite. FastAPI authenticates bearer JWTs and queries PostgreSQL. It calls Ollama for bounded classification and GitHub/Jira for access provisioning. A separate Windows agent uses a per-device bearer token to claim and report WinGet tasks. Render and Vercel configuration, Atlassian and GitHub accounts, and the employee computer are separate trust domains.

Existing controls include PBKDF2-SHA256 at 600,000 rounds with legacy bcrypt verification (`auth.py:11`), HS256 pinning and a 32-character JWT secret minimum (`auth.py:15,30`), generic invalid-credential login text with a dummy password hash (`app/main.py:134-161`), server-side employee approval checks (`auth.py:39-61`), parameterized ORM queries, per-user chat throttling, per-user idempotency constraints, strict input base models, request ownership checks, fixed WinGet package IDs, and backend-only provider tokens. These controls require regression tests during implementation; their presence alone does not prove every boundary.

## HTTP route and data inventory

`Public` means no authentication dependency; `User` means `get_current_user` checks a bearer JWT and employee approval; `Admin` means `require_admin`; `Agent` means a registered active device token. Path parameters are scalar IDs or keys. Input schemas named below are in `app/schemas.py`; endpoints without a body accept path/query input only. All route definitions are in `app/main.py`.

| Routes | Boundary and input | Data read or changed |
| --- | --- | --- |
| `GET /` | Public, no body | Static service health string. |
| `GET /db-test` | Admin, no body | Executes `SELECT 1`; reveals database availability. |
| `POST /auth/register` | Public, `Register` | Creates user, password hash and audit row; returns token including pending users. Admin path checks a shared invite code. |
| `POST /auth/login` | Public, `Login` | Reads user/password hash, writes login audit, returns token and user. |
| `GET /auth/password-recovery` | Public, no body | Returns configured Microsoft recovery destination. |
| `GET /auth/me` | User, no body | Reads current user. |
| `GET /notifications`; `POST /notifications/{id}/read` | User, ID on mutation | Lists own notices; marks an own notice read. |
| `GET /users`, `GET /admin/users`; `PATCH /admin/users/{id}/approval`; `POST /users`; `PUT /users/{id}`; `DELETE /users/{id}` | Admin; `UserApprovalUpdate`, `Register`, `UserUpdate` on writes | Lists/creates/updates/deletes users and approval state; audit rows. Legacy aliases remain. |
| `POST /requests`, `POST /ai/request` | User, `RequestIn` | Rate limits/classifies message, creates or advances own ticket, may create software/access record; audits. |
| `GET /requests`; `GET /requests/{id}`; `GET /requests/{id}/history` | User, ID on detail/history | Own tickets and associated audit entries; admins can view non-password tickets by ID. |
| `POST /requests/{id}/close`, `POST /requests/{id}/resolution`; `POST /requests/{id}/retry-action` | User; `TicketCloseIn` on close/resolution | Mutates own ticket outcome or retries action; audit. |
| `POST /requests/{id}/password/action` | User, ID | Checks own password ticket, records action and returns allowlisted Microsoft URL. |
| `GET /software/catalog`; `POST /software/requests` | User; `SoftwareInstallIn` on write | Reads enabled software policy or queues own device task/ticket. |
| `GET /admin/requests`; `POST /admin/requests/{id}/close`; `POST /admin/requests/{id}/reject` | Admin; `TicketRejectIn` for rejection | Lists all tickets, closes/rejects eligible tickets; audit. |
| `GET /devices` | User | Lists assigned devices. |
| `POST /agent/register` | Admin, `DeviceIn` | Creates device, returns one-time token; stores digest. |
| `GET /agent/heartbeat`; `GET /agent/tasks`; `POST /agent/tasks/{id}/result` | Agent, `ResultIn` on result | Updates device last seen, atomically claims own pending tasks, reports/verifies own task result and ticket. |
| `GET /admin/settings/ticket-closure`; `PUT /admin/settings/ticket-closure` | Admin; `TicketClosureSettingIn` on write | Reads/updates closure policy; audit. |
| `GET /admin/devices`; `PATCH /admin/devices/{id}` | Admin; `DeviceState` on write | Lists devices, enables/disables device token use; audit. |
| `GET /admin/audit`; `GET /admin/audit/requests/{id}/history` | Admin, ID on detail | Lists employee requests and their audit history. |
| `GET /catalog`; `GET /access/applications` | User | Reads software/application policy catalog. |
| `PUT /admin/software/{key}`; `PUT /admin/applications/{key}` | Admin, `PolicyIn` | Updates legacy software or application controls; audits/versioning. |
| `GET /access/requests`; `GET /access/requests/{id}`; `POST /access/requests` | User; `AccessSubmit` on write | Reads own access requests or creates own policy decision/ticket. |
| `GET /admin/access/applications`; `POST /admin/access/applications`; `PUT /admin/access/applications/{key}`; `GET /admin/access/applications/{key}/revisions` | Admin; `ApplicationIn` on writes | Reads/writes policy and immutable revision rows. |
| `GET /admin/access/requests`; `GET /admin/access/pending`; `POST /admin/access/requests/{id}/decision`; `POST /admin/access/requests/{id}/provisioning/retry`; `POST /admin/access/requests/{id}/provisioning/verify` | Admin; `AccessDecisionIn` on decision | Lists/decides/retries access grants, calls configured providers, updates tickets/notices/audits. |
| `GET /admin/github-identities`; `PUT /admin/users/{id}/github-identity` | Admin; `GitHubIdentityIn` on write | Lists and binds verified GitHub identities to employees; external lookup and audit. |
| `GET /docs`, `GET /redoc`, `GET /openapi.json` | Public FastAPI defaults | Exposes full API schema in production unless disabled. |

## Ranked findings

No Critical exploit is confirmed from source alone. High findings include identity and token lifecycle weaknesses; production exposure and impact require validation. `Open` means not fixed in Phase 0. The proposed changes may require coordinated backend/frontend migration and are not silently assumed safe.

| ID | Severity | Evidence | Impact and proposed fix | Status |
| --- | --- | --- | --- | --- |
| A01 | High | `app/main.py:117-161`, `app/schemas.py:18-25` | Admins can register with a reusable shared code; signup does not verify email ownership. Add expiring single-use invites or limited code attempts and single-use email verification before approval. Existing pending-account UI must be preserved. | Open; mail provider manual. |
| A02 | High | `auth.py:24-61`, `frontend/src/App.jsx:16-23,57` | JWTs have no `iat`, `jti`, issuer or audience, no server revocation, and logout only clears browser state. Stolen tokens remain valid until expiry; admin role/status changes are checked on request, but other sessions cannot be individually ended. Add short access tokens, rotating refresh token store, server revocation and logout; test legacy-token migration and Vercel rewrite/cookie behavior. | Open. |
| A03 | High | `app/main.py:117-161`, `app/chat_limits.py:1-73` | Only chat is throttled; login, registration and invite attempts can be repeated. Add persisted per-account and per-IP limits with `429`/`Retry-After`, without account enumeration. | Open. |
| A04 | High | `app/schemas.py:25,51-55`, `frontend/src/App.jsx:176-177` | Six-character passwords and no common/breached password checks allow weak credentials. Raise policy with existing-account migration plan and safe server-side common-password checks; test without sending passwords to a third party. | Open. |
| A05 | High | `frontend/src/App.jsx:16-23`, `frontend/vercel.json:1-19` | Bearer access token in sessionStorage is readable by injected JavaScript; no CSP header is configured. Evaluate same-origin cookie refresh through Vercel rewrite, CSRF and deployment constraints. Apply strict CSP and XSS checks even if token storage remains. | Open. |
| A06 | High | `app/main.py:64-66`, `frontend/vercel.json:1-19` | No explicit CORS policy, API response security headers or production OpenAPI restriction. Cross-origin browser use is limited by absence of CORS middleware, but defense and header posture are incomplete. Add explicit allowed origins, CSP and related headers; gate docs in production. | Open. |
| A07 | Medium | `auth.py:48-54`, `app/main.py:134-156` | Admin approval status is not checked for admins; role mismatch and pending-account responses reveal account state to a caller with the password. Preserve required pending-login UX while removing avoidable enumeration and revoking admin sessions when required. | Open. |
| A08 | Medium | `app/schemas.py:6,91-100`, `app/main.py:95-115`, `app/workflows.py:91-105` | Input schemas forbid extra fields and chat length is bounded, but request body bytes have no global cap; large JSON can consume resources before validation. Add a bounded body middleware and tests. Idempotency keys are correctly scoped by `user_id`; retain this control. | Open; idempotency scoped. |
| A09 | Medium | `app/main.py:182-186,318-322,620-625,680-684`, `app/workflows.py:54-59` | Lists have hard result limits but no page traversal; object checks are distributed across routes. Audit ID-based access with cross-user tests and add capped pagination without leaking user records. | Open; basic ownership guards present. |
| A10 | Medium | `app/main.py:68-84`, `app/database.py:1-6` | Several exception classes are handled, but no correlation ID or structured redacted error log exists. Add generic 500 handling with request ID, safe server logs and no leaked internals. Dynamic migration SQL interpolates only code-owned identifiers (`app/database.py:22,91`); keep it inaccessible to input. | Open. |
| A11 | Medium | `app/main.py:446-470,610-619`, `app/models.py:32-42` | Device tokens are random and stored as SHA-256 digests, and disabling a device blocks use. There is no rotate-token operation; a copied active token works until disabled. Add per-device rotation with a one-time replacement token and replay/ownership tests. | Open. |
| A12 | Medium | `app/models.py:12-20`, `app/workflows.py:19-21`, `app/main.py:620-636` | Date of birth and email are retained; audit rows are application append-only but have no tamper-evident chain or retention policy. Minimize data and consider a hash chain with migration/backfill tests. | Open. |
| A13 | Medium | `app/database.py:1-6`, `render.yaml:1-54` | Code does not enforce PostgreSQL TLS or least-privilege account, and no tested backup/restore procedure or monitoring configuration is recorded. Require SSL in production and document role, alert, and scratch-restore steps. | Open; infrastructure manual. |
| A14 | Medium | `.github/workflows/ci.yml:1-30`, `.github/workflows/endpoint-agent.yml:1-40` | CI runs tests and builds but lacks dependency audit, static security analysis, secret scan, and update automation. Add pinned tools/scanners and a failing gate for actionable findings. | Open. |
| A15 | Low | `endpoint_agent/installer.py:1-48`, `endpoint_agent/config.py:1-35`, `endpoint_agent/agent.py:9-77` | Agent already uses exact package IDs, argument lists, HTTPS outside localhost and backend task age limits; replay/report handling needs targeted tests. Verify installation result semantics and enforce any missing local task-age bound. | Open; baseline mitigations exist. |
| A16 | Low | `app/github_provider.py:1-110`, `app/jira_provider.py:1-111`, `agent.py:1-160` | Provider clients have timeouts and fixed API origins; classifier output is validated, but adversarial prompt and error-path coverage is incomplete. Add tests for encoded prompts, malformed provider responses and secret-safe retries. | Open. |
| A17 | Low | `.gitignore:1-18`, `frontend/vercel.json:1-19` | `.env` is ignored, but history was not scanned and frontend build variables were not checked for secrets. Run a history secret scanner and add a CI check for `VITE_` exposure. Do not print findings' secret values. | Open. |

## Manual actions and verification required

- Choose an email delivery service and sender domain; verification cannot work for real users until configured.
- Choose MFA enforcement and account recovery policy for administrators; recovery codes need a controlled delivery/storage process.
- Configure Render/Vercel origin, cookie domain and production secrets during the coordinated session migration. Confirm Render deployment and Vercel rewrite behavior without logging tokens.
- Supply a least-privilege PostgreSQL application role, SSL settings, backup storage and an isolated restore target. Never run a restore check against production.
- Configure GitHub expiry cron, provider token rotation, monitoring and alert destinations in the respective services.
- Decide acceptable retention for date of birth, request history, agent records and audit logs.

## Phase order

1. Authentication, signup and session design, including explicit migration/breaking-change review.
2. Authorization and cross-user regression tests.
3. Input bounds, rate limits, AI/provider validation and safe errors.
4. Browser/API headers and deployment configuration.
5. Secrets, data, agent/provider controls, CI and recovery documentation.

This Phase 0 report makes no code or production-state changes.
