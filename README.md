# AutoDeskAI

AutoDeskAI is an IT helpdesk prototype with a FastAPI backend, PostgreSQL database, React frontend, Ollama request classification, and a Windows endpoint agent. It handles organization password help and application access requests. Approved Visual Studio Code requests create endpoint tasks that install the package through WinGet and verify it on the device.

For a full explanation of the project's purpose, users, workflows, architecture, security measures, and expected impact, see [Project Documentation](PROJECT_DOCUMENTATION.md).

## Current behavior

- Employees and administrators register with first name, last name, date of birth, username, email, and password. New employee registrations remain pending until an administrator authorizes or rejects them in the Admin Panel. The panel keeps separate Pending, Approved, Rejected, and Deauthorized filters; an approved account can be deauthorized or later authorized again. These statuses persist in the user record and every change is audited. A deauthorized account cannot sign in or use an existing token on the next API request. Invited administrator registrations are approved by the private `ADMIN_REGISTRATION_CODE` configured on the backend. Sign in with username or email through the matching employee or admin portal.
- The browser keeps the access token in tab session storage. Reloading the tab restores the account through `GET /auth/me`; an expired token requires sign-in again. Storage lasts for the browser tab's session.
- The assistant handles organization password change/reset, application access, clarification, help, and the signed-in user's own request statuses. It queues approved Visual Studio Code installations for active, connected Windows devices and rejects unsupported software or ineligible devices. General questions, prompt-injection attempts, and unrelated tasks receive a fixed scope response and are not sent to Ollama. Only a sanitized representation of workflow messages reaches the classifier. Raw messages are not stored; tracked service requests retain only their sanitized allowed-token representation.
- Authenticated chat submissions use persistent per-user PostgreSQL counters: 10 per minute, 60 per hour, and 5 consecutive out-of-scope attempts per minute by default. Requests over a limit return HTTP 429 with `Retry-After`. Messages are limited to 2,000 characters.
- Password change requests open Microsoft's hosted My Account. Organization password reset uses Microsoft Entra SSPR at the configured `MICROSOFT_SSPR_URL` (default `https://passwordreset.microsoftonline.com/`). The backend records when the employee chooses **Continue at Microsoft**, but cannot verify the outcome and leaves reset requests at `AWAITING_USER_ACTION`. The AutoDeskAI login password is separate.
- Software installation uses WinGet on a registered Windows endpoint; the agent verifies the package before reporting success. Application access uses configurable backend policies. GitHub organization membership and Jira workspace group access have provider integrations. A verified external grant is recorded as `GRANTED`; a simulated or unconfigured provider never counts as a grant.
- Administrators can review requests, users, devices, audit history, and application catalog and approval policies. They can decide pending access requests, enroll and disable endpoint devices.
- Rejected requests close automatically without asking for employee confirmation. The request records whether AutoDeskAI or an administrator rejected it, and the detail view shows that source as its resolution. Existing closed rejections are attributed during startup migration.
- Employees use Resolved / Not resolved controls beside the chat composer only for requests that still need their outcome; the chat no longer shows a duplicate next-step card. Administrator approval or rejection closes the helpdesk ticket directly, while application provisioning remains tracked separately. For password requests, the chat waits until **Continue at Microsoft** was chosen before showing that confirmation; it never treats opening the link as proof of success. The same request gate applies to quick actions and the application access form. A password action is offered once more after the first unresolved report; a second unresolved report raises the same issue to an administrator and displays an in-app admin alert. Requests without a safe employee retry path, such as application access, are escalated directly. Administrators can resolve or reject escalated requests. A resolved report closes the ticket and is stored with its audit history; the outcome is self-reported, not provider verification.
- Ticket closure policy controls whether a verified installation result needs administrator closure. Employee resolution is tracked separately from endpoint verification and application provisioning results.
- The request detail view shows the issue, current status, employee-reported resolution, and full event history without pagination. The visible `Ticket #` prefix has been removed from ticket labels. Pagination on larger lists uses the application's teal theme.
- The admin Audit Logs page lists only employee-created requests, with usernames supplied by the backend. Each request can be opened to see what the employee asked for, its current outcome or completion, and the request's audit history. Login and policy events remain recorded internally but do not appear in this request list.
- The interface uses a shared teal workspace design across sign-in, employee support, access approvals, administration, and audit. Desktop navigation uses a sidebar; the mobile drawer supports keyboard focus and Escape. Request filters, quick chat starters, status summaries, and request timelines help employees and administrators find the next action. Both light and dark themes are supported.

## Research foundation and scope

This project is based on Mani et al., *Hi, how can I help you?: Automating enterprise IT support help desks* (AAAI, 2018). AutoDeskAI applies the paper's help desk workflow ideas to a deliberately small, policy controlled prototype. It is not a full reproduction of the paper's QA platform.

| Paper concept | AutoDeskAI implementation | Current boundary |
| --- | --- | --- |
| Orchestrate multiple IT support components | The backend routes password and application access requests to their workflows. Approved Visual Studio Code requests are queued for a registered endpoint agent. | The model classifies sanitized intent; backend code controls decisions. |
| Resolve ambiguity through clarification | Ambiguous or incomplete requests can enter `NEEDS_CLARIFICATION`; a follow-up is tied to that request and validated before it continues. | Clarification uses a small set of supported workflow and catalog entities, not the paper's learned QA corpus. |
| Keep a human in the loop | Application policies can require administrator approval; high risk and human only roles cannot be auto approved. Users initiate the request, and password completion remains with the user and Microsoft. | There is no general live support handoff or SME authoring queue. |
| Automate suitable resolution steps | Access decisions can use configured automatic approval rules. | GitHub membership and Jira group and product access can be verified through configured providers; unsupported entries stay simulated or unconfigured. Approved Visual Studio Code installation is live on Windows endpoints. |
| Learn from support interactions | Requests and administrator decisions are audited for operational review. | Audit history is not used to retrain a classifier or automatically create knowledge answers. Continuous learning is not implemented. |
| Ingest enterprise knowledge and answer questions from it | The application catalog and fixed workflow guidance provide limited, controlled support information. | There is no ingestion pipeline for documents, tickets, images, audio, or video, and no retrieval augmented QA system. General questions are out of scope. |

### Access decision model

For an access request `r`, employee account `u`, and application policy `p`, the implemented outcomes are:

\[
D(r,u,p)=\begin{cases}
\text{Clarify}, & \text{if required request details are unclear or missing}\\
\text{Reject}, & \text{if the app is disabled, the requester or role is ineligible, or a failed check uses a DENY fallback}\\
\text{Auto-approve}, & \text{if policy permits automation and all required checks pass}\\
\text{Admin review}, & \text{if policy requires a person or required checks are unverified and fallback requires approval}
\end{cases}
\]

There is no separate `Block` decision in the current access evaluator. Requests outside supported chat scope receive a fixed response and are not submitted as access requests. A required fact the system cannot verify (for example, directory group membership or MFA) cannot pass automatic approval; it follows the application's configured fallback. Approval only authorizes a provisioning attempt and does not confirm that access was granted.

The employee-reported resolution metric is:

\[
\text{Employee-reported resolution rate}=\frac{\text{closed tickets marked resolved by employees}}{\text{closed tickets with a recorded resolution outcome}}\times 100\%
\]

This measures employee reports, not independently verified fixes. Tickets with no recorded outcome are excluded from the denominator. The project records outcomes and history but does not currently show this rate as a dashboard metric.

The paper's key design principles for this prototype are orchestration, explicit clarification, backend-owned decisions, appropriate human approval, and truthful reporting of action outcomes. The intentionally unimplemented research components above should be treated as future scope, not as existing features. Any expansion to knowledge ingestion or learned answers should add source tracking, access controls, and human review before answers or policies affect users.

## Requirements

Python 3.11+, PostgreSQL, Node.js 20.19+ or 22.12+, and an accessible Ollama model. `requirements.txt` contains runtime Python packages; `requirements-dev.txt` adds pytest for local and CI tests. The frontend packages are in `frontend/package.json`.

## Run locally

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Create an empty PostgreSQL database and set its `DATABASE_URL` in the ignored `.env` file. Use `postgresql+psycopg://...` and percent-encode special characters in credentials. Set a private JWT signing key of at least 32 characters:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; from dotenv import set_key; set_key('.env', 'JWT_SECRET_KEY', secrets.token_urlsafe(48))"
```

Set `ADMIN_REGISTRATION_CODE` privately if administrators should register through the UI. Set `OLLAMA_HOST`, `OLLAMA_MODEL`, and, for a hosted model, `OLLAMA_API_KEY`. The local defaults in `.env.example` use `qwen3:8b` at `http://localhost:11434`; install and start that model or choose one you have available. Keep `.env` out of source control.

Set backend runtime variable `MICROSOFT_SSPR_URL` to `https://passwordreset.microsoftonline.com/` for the standard work or school account recovery experience. The logged-out frontend reads this value from the public `/auth/password-recovery` endpoint, so no duplicate Vercel build variable is required. Configure `MICROSOFT_SSPR_URL` in the Render service's environment settings (or keep the standard default in `render.yaml`). Vercel needs no SSPR environment variable; its existing `/api` rewrite forwards the public configuration request to Render. Only this approved HTTPS Microsoft SSPR host is accepted.

In Microsoft Entra, an administrator must enable SSPR for the intended users (or group), configure allowed authentication methods and registration, and configure password writeback if synchronized on-premises accounts must be reset in the cloud. Licensing and hybrid writeback requirements depend on the tenant. If a user is not enabled, lacks registered verification methods, or the tenant requires administrator assistance, Microsoft displays its own guidance; users should contact their IT administrator. Test with a dedicated test account only. Password reset is recovery after forgetting a password; `PASSWORD_CHANGE` is for a user who knows the current password and continues through Microsoft My Account. AutoDeskAI does not receive credentials or verify reset completion. See [Microsoft's SSPR overview](https://learn.microsoft.com/en-us/entra/identity/authentication/concept-sspr-howitworks), [enablement guide](https://learn.microsoft.com/en-us/entra/identity/authentication/tutorial-enable-sspr), and [work or school password help](https://learn.microsoft.com/en-us/microsoft-365/troubleshoot/sign-in/forgot-sign-in-password).

Start the backend and frontend in separate terminals:

```powershell
.\.venv\Scripts\python.exe check_services.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open `http://127.0.0.1:5173/`. Vite proxies `/api` to FastAPI. API documentation is at `http://127.0.0.1:8000/docs`.

Register through the appropriate portal. The administrator invite code must match the backend setting and should be shared only with intended administrators. After an administrator enrolls a device, copy its one-time agent token into the endpoint's ignored `.env` along with `SERVER_URL` and `DEVICE_ID`. The backend stores only a digest of this token. Set `AGENT_INSTALL_MODE=real` in the endpoint environment and start the agent in the signed-in Windows user's session. WinGet must be available to that user:

```powershell
.\.venv\Scripts\python.exe -m endpoint_agent.agent
# Or perform one heartbeat and task cycle:
.\.venv\Scripts\python.exe -m endpoint_agent.agent --once
```

The endpoint agent installs approved Visual Studio Code through WinGet with an exact package ID, user scope, and noninteractive flags. Enroll a Windows device, run the agent, and select its connected device in chat before requesting installation. The agent checks WinGet's installed-package list before reporting success.

## Workflows

### Application access

The employee **Application Access** page loads enabled entries from `GET /access/applications`. Employees choose an application, one of its requestable roles, a duration, and a business justification. Their JWT determines the requester; `GET /access/requests` and `GET /access/requests/{id}` return only their own records. Tableau and Power BI are hidden from the employee and administrator catalogs. Existing policies are disabled at startup; prior request history is retained.

The admin **Application Access** page creates and edits entries, shows the approval queue, records decisions, and displays request history, policy versions, evaluated conditions, and provisioning status. Approval does not require an administrator reason; rejection requires a reason. `POST /admin/access/applications` creates an entry; `PUT /admin/access/applications/{key}` increments its version and stores an immutable snapshot in `access_policy_revisions`. Existing requests retain their evaluated policy version. The older `PUT /admin/applications/{key}` route remains available for its enabled/role controls and also increments the version.

When an application access request is approved or rejected, the requester receives a stored notification. This includes direct chat denials, automatic policy decisions, and later administrator decisions. An unread decision appears as a visible notice and in the employee portal bell. The portal refreshes notices while open and retains unread decisions across sessions. Opening a notice marks it read and takes the employee to their request. Approval notices explain that approval is not yet an access grant. `GET /notifications` lists only the signed-in user's notices, and `POST /notifications/{id}/read` marks one of their notices read.

GitHub and Jira remain the seeded application examples. Tableau and Power BI policies are disabled and omitted from both catalogs, with historical requests preserved; Power BI live setup is not active. Admins can edit active policies and add applications; catalog registration alone does not create an integration. Policies have `AUTOMATIC`, `CONDITIONAL`, and `ADMIN_ONLY` modes, requestable and human-only roles, allowed groups, durations, risk, conditions, and `REQUIRE_ADMIN_APPROVAL` or `DENY` fallback. Automatic approval requires `auto_allowed`, an eligible low/medium-risk role, and every condition to pass. High-risk and human-only roles always require an administrator. The local JWT has no trusted directory group, HR employment, or verified MFA claims, so those conditions evaluate as **unverified** and take the fallback. A failed condition also takes the fallback. The evaluator records its condition results, decision, fallback and policy version on each request, with audit entries for evaluation and manual decisions. Administrators cannot decide their own requests.

Approval is separate from provisioning. Approved requests use `APPROVED_PROVISIONING_REQUIRED`; they do not become `GRANTED` until a configured provider verifies external access. For GitHub this means active organization membership; for Jira it means the mapped group and product role. The built-in `MOCK` provider validates the application and role, records `SIMULATED`, and makes no external grant. `NONE` records `NOT_CONFIGURED`. A provider timeout or failure is recorded as `TIMEOUT` or `FAILED`; an administrator can retry through `POST /admin/access/requests/{id}/provisioning/retry`. Retry attempts are counted and audited. `config_ref` is only an uppercase configuration *reference*, never a credential, and is omitted from employee catalog responses.

For live GitHub organization access, set `GITHUB_ORG=AutoDeskAI` and a backend-only `GITHUB_TOKEN` with organization **Members: write** permission, granted to an organization owner. In the admin Application Access page, enable the `github` catalog entry with provider `GITHUB_ORG`, sole requestable role `member`, and `ADMIN_ONLY` approval. The employee enters their GitHub username in the access request. The server checks the public GitHub user ID and stores it with the request. The administrator reviews the account shown on the request and confirms it belongs to the employee before approving. Approval checks current membership and invites the user only if absent. An invitation stays `PENDING_ACCEPTANCE`; the administrator uses **Verify GitHub membership** after acceptance. Only confirmed active membership marks the request `COMPLETED` with provisioning status `GRANTED`. A missing token records `NOT_CONFIGURED` and can be retried after setup. The configured organization is snapshotted on the request, so configure the token and organization before employees submit requests. The connected ChatGPT GitHub account is separate from the backend token.

GitHub expiry has a scheduled worker in `app/github_expiry.py` and a daily UTC cron service in `render.yaml`. The cron service requires its own `DATABASE_URL` and `GITHUB_TOKEN` on Render; it is not active until that service is created and configured. It revokes only membership created by AutoDeskAI, checks the GitHub user ID and membership before deletion, verifies absence afterwards, and records failures for retry and administrator review. Membership shared with another unexpired request is retained. An unmanaged pre-existing membership is never revoked. The GitHub token needs organization Members write permission. Render cron jobs incur a monthly charge; review that before creating the service. This provider covers organization `member` access only, not repository or team permissions.

### Retired Tableau Cloud connector

The Tableau provider code remains for historical compatibility. Tableau is hidden from the application catalogs and existing policies are disabled.

The legacy connector uses a Tableau Cloud site administrator token to find or create a site user and verify the assigned site role. It is retained for historical compatibility only. Tableau cannot be selected from the current employee or administrator catalog; prior access requests remain in history.

### Jira Cloud group access

Set backend-only `JIRA_SITE_URL` to the HTTPS `*.atlassian.net` site, `JIRA_ADMIN_EMAIL` and `JIRA_API_TOKEN` to a site administrator's email and unscoped API token, `JIRA_PRODUCT_KEY` to the intended product role key (for example `jira-software`), and `JIRA_ROLE_MAP` to JSON mapping catalog roles to stable Jira group IDs (for example `{"user":"actual-group-id"}`). Configure the target group to grant the intended Jira product access. Set these before a request is submitted; the site hostname is recorded on the request. In admin Application Access, set the `jira` entry to provider `JIRA` and keep `ADMIN_ONLY`. The administrator must independently verify ownership of the requester's email before approving. The provider requires an existing active Atlassian user with an exact visible email match. It adds the account to the mapped group, then verifies group membership and the specified product role. An absent user returns `USER_NOT_FOUND`; a hidden or ambiguous email returns `IDENTITY_MISMATCH`; a missing product role returns `PRODUCT_ACCESS_REQUIRED`. These remain ungranted and can be retried after an administrator fixes the account or site configuration. Automatic invitation is not implemented because Atlassian's current organization invitation API requires a paid subscription. This connector is tested with mocked API responses only; it does not manage project roles or revoke group membership on expiry.

At startup, `upgrade_application_access()` adds catalog, access-request, and rejection-source columns to existing installations without deleting records. It attributes previously closed rejections where the closure record identifies a denial. A new `access_policy_revisions` table is created by SQLAlchemy. Legacy demo approvals that explicitly said no external access was provisioned are corrected to `APPROVED_PROVISIONING_REQUIRED` and audited. Existing pending installation tasks remain queued and are handled by the endpoint agent or timed out. The backend deploy on Render runs this migration at startup; Vercel's existing `/api` rewrite already forwards the new routes. No new environment variables are required for the mock provider.

### Employee resolution and ticket closure

For password requests and other open requests requiring user feedback, the employee can choose **Resolved** or **Not resolved** beside the chat composer. An administrator's approval or rejection closes the helpdesk ticket without employee confirmation; the access request continues to show provisioning status in Application Access. Choosing resolved closes the ticket and records the reporter, outcome, and audit event. Choosing not resolved offers one retry for password actions or escalates requests without a safe retry path. Administrators can resolve or reject escalated tickets, providing a reason for rejection. After a live software task reports a result, the employee confirms whether the issue was resolved. Unsupported software requests close as rejected.

The chat and Application Access page show the open request's issue text, status, and resolution state. Every submitted chat message appears in the conversation before the assistant replies, including when a current request prevents new work. Dashboard quick actions use the same chat flow. The chat does not display a separate next-step card that repeats the assistant's message. Chat history survives page reloads and the Microsoft round trip in the same browser tab, and is cleared on sign-out; raw chat text is not stored in the backend. When an application name is requested, an available answer such as Jira advances the same ticket, while an unrelated request receives a reminder to answer the pending question. The admin request list shows request type without a ticket number. Opening request details shows the complete history at once; only larger lists use pagination.

| Request | Result |
| --- | --- |
| “I forgot my password” | Creates a reset request and offers Microsoft's hosted reset page. Completion remains unverified. |
| “I need to change my password” | Creates a change request and offers Microsoft My Account. Completion remains unverified. |
| "Install VS Code" | Queues a live install for a selected connected Windows endpoint. The agent verifies the installed package before reporting success. |
| “I need access to Jira” | Requires an existing active Atlassian account with a matching visible email. Administrator approval closes the helpdesk ticket; Jira group and product access is tracked separately and is granted only after verification. |
| “Hello” or “help” | Receives a fixed help response without a request record or model call. |
| “What is the status of my requests?” | Shows the signed-in user's 10 most recent statuses without exposing request text. |
| General questions or unrelated tasks | Receives a fixed out-of-scope response; no model call or request record is created. Repeated attempts are rate limited. |

The employee dashboard shows tracked request counts. Requests refresh while work is pending; device data refreshes periodically. Polling pauses when the tab is hidden, avoids overlapping reads, and refreshes relevant data after actions.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest test.py -q
cd frontend
npm.cmd test
npm.cmd run build
```

The Python tests use an isolated in-memory SQLite database and mocked model and WinGet responses. They do not clear PostgreSQL or install software. `demo_e2e.py --live-install` is a separate integration check that installs Visual Studio Code on the Windows machine running it and retains demo records in the configured database; use it only on a designated test endpoint and database.

## Deployment

The Vercel frontend uses `frontend/vercel.json` to forward `/api` to `https://autodeskai-backend.onrender.com`. If the Render backend URL changes, update those rewrites. The Render service is defined in `render.yaml`. Configure its private `DATABASE_URL`, `ADMIN_REGISTRATION_CODE`, and `OLLAMA_API_KEY` as needed; Render generates `JWT_SECRET_KEY`. The database URI should use the PostgreSQL session pooler with SSL when required by the provider. Never put backend secrets in Vercel frontend variables.

The Render blueprint configures Ollama Cloud and chatbot limits. The backend environment variables are `CHAT_RATE_LIMIT_PER_MINUTE` (default `10`), `CHAT_RATE_LIMIT_PER_HOUR` (`60`), `CHAT_OUT_OF_SCOPE_LIMIT_PER_MINUTE` (`5`), and `CHAT_MAX_MESSAGE_LENGTH` (`2000`, hard maximum 2,000). Set these on Render as backend runtime variables when changing defaults; `.env.example` contains the local values. No Vercel frontend build variable is required. The `chat_rate_limit_buckets` table is created automatically at backend startup and shares counters across Render instances. Local development can use a locally hosted Ollama server. A remote endpoint agent must reach the backend over HTTPS. A sleeping Render free service can delay the first request.

## API

| Area | Routes |
| --- | --- |
| Authentication | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Requests | `POST /requests` (alias `POST /ai/request`), `GET /requests`, `GET /requests/{id}`, `GET /requests/{id}/history`, `POST /requests/{id}/resolution`, `POST /requests/{id}/retry-action` |
| Password action | `POST /requests/{id}/password/action` |
| Employee data | `GET /devices`, `GET /catalog`, `GET /access/applications`, `POST /access/requests`, `GET /access/requests`, `GET /access/requests/{id}`, `GET /notifications`, `POST /notifications/{id}/read` |
| Endpoint agent | `POST /agent/register`, `GET /agent/heartbeat`, `GET /agent/tasks`, `POST /agent/tasks/{id}/result` |
| Administration | `GET /admin/users`, `GET /admin/requests`, `GET /admin/devices`, `GET /admin/audit`, `/admin/access/applications`, `/admin/access/pending`, `/admin/access/requests`, `/admin/access/requests/{id}/decision`, policy and device update routes |
| Health | `GET /`, admin-only `GET /db-test` |

Request creation uses a client-generated `idempotency_key`; retry an uncertain submission with the same key. A clarification reply supplies the owned request's `previous_request_id`. In-scope chat/help/status and out-of-scope replies return HTTP 200 with intent `CHAT` and no request ID; created requests return HTTP 201. Chat submissions require a valid AutoDeskAI JWT. Limits are applied before any model call; HTTP 429 includes `Retry-After` seconds.

Startup creates missing tables, upgrades the existing user profile columns and lookup indexes, and seeds the VS Code software policy and active GitHub and Jira access examples. Existing Tableau and Power BI policies are disabled and hidden without deleting their request history. It does not clear the database. The one-off `_db_clear_once.py --delete` script **deletes all app records and restarts IDs**; running it against a live database removes all accounts, requests, audit records, devices, and policies.

## Limits

Organization password actions are links to Microsoft; there is no provider callback, local account recovery, or automatic password update. Software installation is live for approved Visual Studio Code requests on connected Windows endpoints; unsupported software and ineligible device requests are rejected and closed. GitHub organization membership and Jira group and product access have provider implementations, but require tenant credentials and policy configuration for live grants. VS Code is the predefined software entry; GitHub and Jira are the active access catalog examples. Tableau and Power BI are retired from the catalogs. JWTs expire without a refresh-token flow. Signup does not verify email ownership.
