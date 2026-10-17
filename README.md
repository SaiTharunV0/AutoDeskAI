# AutoDeskAI

AutoDeskAI is an IT helpdesk prototype with a FastAPI backend, PostgreSQL database, React frontend, Ollama request classification, and a simulated endpoint agent. It handles organization password help, approved software installation requests, and application access requests. Backend policy, account roles, and device ownership control the workflows.

## Current behavior

- Employees and administrators register with first name, last name, date of birth, username, email, and password. Administrator registration requires a private `ADMIN_REGISTRATION_CODE` configured on the backend. Sign in with username or email through the matching employee or admin portal.
- The browser keeps the access token in tab session storage. Reloading the tab restores the account through `GET /auth/me`; an expired token requires sign-in again. Storage lasts for the browser tab's session.
- The assistant is limited to organization password change/reset, approved software installation, application access, clarification, help, and the signed-in user's own request statuses. General questions, prompt-injection attempts, and unrelated tasks receive a fixed scope response and are not sent to Ollama. Only a sanitized representation of supported workflow messages reaches the classifier. Raw messages are not stored; tracked service requests retain only their sanitized allowed-token representation.
- Authenticated chat submissions use persistent per-user PostgreSQL counters: 10 per minute, 60 per hour, and 5 consecutive out-of-scope attempts per minute by default. Requests over a limit return HTTP 429 with `Retry-After`. Messages are limited to 2,000 characters.
- Password change requests open Microsoft's hosted My Account. Organization password reset uses Microsoft Entra SSPR at the configured `MICROSOFT_SSPR_URL` (default `https://passwordreset.microsoftonline.com/`). AutoDeskAI cannot verify the outcome and leaves reset requests at `AWAITING_USER_ACTION`. The AutoDeskAI login password is separate.
- VS Code installation is simulated by an enrolled, online endpoint agent. Tableau access is a backend policy decision; it does not provision an external account.
- Administrators can review requests, users, devices, audit history, and existing software and application policies. They can enroll and disable endpoint devices.

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

Register through the appropriate portal. The administrator invite code must match the backend setting and should be shared only with intended administrators. After an administrator enrolls a device, copy its one-time agent token into the endpoint's ignored `.env` along with `SERVER_URL` and `DEVICE_ID`. The backend stores only a digest of this token. Keep `AGENT_SIMULATION_MODE=true` and start the agent:

```powershell
.\.venv\Scripts\python.exe -m endpoint_agent.agent
# Or perform one heartbeat and task cycle:
.\.venv\Scripts\python.exe -m endpoint_agent.agent --once
```

Wait for a heartbeat before submitting an installation request. The agent only simulates installation; real installation mode is not implemented.

## Workflows

| Request | Result |
| --- | --- |
| “I forgot my password” | Creates a reset request and offers Microsoft's hosted reset page. Completion remains unverified. |
| “I need to change my password” | Creates a change request and offers Microsoft My Account. Completion remains unverified. |
| “Install VS Code” | Requires an active enrolled device with an online agent and an enabled software policy. The agent reports a simulated result. |
| “I need access to Tableau” | Applies the configured access policy and records a demo approval or rejection. |
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

The Python tests use an isolated in-memory SQLite database and mocked model responses. They do not clear PostgreSQL. `demo_e2e.py` is a separate live integration check that creates and retains demo records in the configured database; run it only against a database where that is acceptable.

## Deployment

The Vercel frontend uses `frontend/vercel.json` to forward `/api` to `https://autodeskai-backend.onrender.com`. If the Render backend URL changes, update those rewrites. The Render service is defined in `render.yaml`. Configure its private `DATABASE_URL`, `ADMIN_REGISTRATION_CODE`, and `OLLAMA_API_KEY` as needed; Render generates `JWT_SECRET_KEY`. The database URI should use the PostgreSQL session pooler with SSL when required by the provider. Never put backend secrets in Vercel frontend variables.

The Render blueprint configures Ollama Cloud and chatbot limits. The backend environment variables are `CHAT_RATE_LIMIT_PER_MINUTE` (default `10`), `CHAT_RATE_LIMIT_PER_HOUR` (`60`), `CHAT_OUT_OF_SCOPE_LIMIT_PER_MINUTE` (`5`), and `CHAT_MAX_MESSAGE_LENGTH` (`2000`, hard maximum 2,000). Set these on Render as backend runtime variables when changing defaults; `.env.example` contains the local values. No Vercel frontend build variable is required. The `chat_rate_limit_buckets` table is created automatically at backend startup and shares counters across Render instances. Local development can use a locally hosted Ollama server. A remote endpoint agent must reach the backend over HTTPS. A sleeping Render free service can delay the first request.

## API

| Area | Routes |
| --- | --- |
| Authentication | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Requests | `POST /requests` (alias `POST /ai/request`), `GET /requests`, `GET /requests/{id}`, `GET /requests/{id}/history` |
| Password action | `POST /requests/{id}/password/action` |
| Employee data | `GET /devices`, `GET /catalog` |
| Endpoint agent | `POST /agent/register`, `GET /agent/heartbeat`, `GET /agent/tasks`, `POST /agent/tasks/{id}/result` |
| Administration | `GET /admin/users`, `GET /admin/requests`, `GET /admin/devices`, `GET /admin/audit`, policy and device update routes |
| Health | `GET /`, admin-only `GET /db-test` |

Request creation uses a client-generated `idempotency_key`; retry an uncertain submission with the same key. A clarification reply supplies the owned request's `previous_request_id`. In-scope chat/help/status and out-of-scope replies return HTTP 200 with intent `CHAT` and no request ID; created requests return HTTP 201. Chat submissions require a valid AutoDeskAI JWT. Limits are applied before any model call; HTTP 429 includes `Retry-After` seconds.

Startup creates missing tables, upgrades the existing user profile columns and lookup indexes, and seeds absent VS Code and Tableau policies. It does not clear the database. The one-off `_db_clear_once.py --delete` script **deletes all app records and restarts IDs**; running it against a live database removes all accounts, requests, audit records, devices, and policies.

## Limits

Organization password actions are links to Microsoft; there is no provider callback, local account recovery, or automatic password update. Software installation and application access are simulations. Only VS Code and Tableau are predefined. JWTs expire without a refresh-token flow. Signup does not verify email ownership. The endpoint agent has no shell execution path and cannot perform a real installation.
