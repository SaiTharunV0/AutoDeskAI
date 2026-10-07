# AutoDeskAI

Authenticated IT helpdesk using FastAPI, SQLAlchemy/PostgreSQL, React/Vite, local Ollama, Microsoft Entra ID, Jira Cloud REST API, and a Windows endpoint agent. The AI classifies sanitized requests; backend policy and device ownership determine every action.

## Recent changes

This implementation preserves the existing backend foundation while completing the local helpdesk workflow, security controls, and agent/device integration. Key updates include:

- Configurable Ollama-based classification with bounded structured outputs, prompt constraints, clarification handling, and validation before actions are dispatched.
- Stronger authentication and authorization, including PBKDF2 password hashing, legacy bcrypt compatibility, expiring JWTs, server-side admin checks, and protected employee/admin APIs.
- PostgreSQL-backed request lifecycle, device ownership checks, audit history, policy enforcement, idempotent submissions, and task tracking with safe retry behavior.
- Microsoft Entra password changes through delegated Microsoft Graph access and reset through Microsoft's hosted SSPR flow, verified against the Entra password-change timestamp. Both are restricted to the configured test account.
- Jira project-role provisioning and verification against the dedicated test account and project. Jira User and Developer can be provisioned by policy; Project Admin remains pending until an administrator approves it.
- Endpoint-agent enrollment and real, allowlisted VS Code/Chrome installs through Windows Package Manager, followed by endpoint verification and idempotent result reporting. Simulation mode is opt-in.
- React/Vite frontend for registration, login, device enrollment, request submission, policy review, admin dashboard, and status polling.
- End-to-end demo and verification scripts for local PostgreSQL/Ollama validation without modifying production credentials.

## What works

- Employee registration, password hashing (PBKDF2-SHA256; existing bcrypt hashes supported), expiring JWTs and server-side employee/admin authorization.
- Password change requests transmit credentials only to the configured Entra test account through Microsoft Graph. Password reset opens Microsoft's hosted SSPR page and checks Entra's `lastPasswordChangeDateTime`; AutoDeskAI never handles the reset password.
- Approved VS Code and Chrome installation tasks are dispatched only to the enrolled Windows device. The endpoint agent uses fixed `winget` package IDs, never invokes a shell, and confirms the executable exists before reporting success.
- Jira role requests are mapped to the fixed `Users`, `Developers`, and `Administrators` project roles and are verified with Jira's REST API. Project Admin requires an administrator decision.
- Request status/history, idempotent submissions, device heartbeat/offline checks, task timeout, audit records, and admin policy/device management.
- React login/registration, employee dashboard, helpdesk, device selection, request history, profile and admin workspace.

No Gemini dependency or API call remains. Neither model output nor user-selected package names are passed to a command runner. The endpoint agent invokes only fixed Windows Package Manager commands.

## Prerequisites

Python 3.11+, PostgreSQL, Node.js 20.19+ or 22.12+, and Ollama with a locally installed model. Commands below run from the repository directory in PowerShell. This workspace already has its environment at `..\.venv`; for a new checkout use `.venv` instead.

## Configure and run

1. Create an environment and install dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

2. Edit the ignored `.env` privately. Set `DATABASE_URL` to a working PostgreSQL database connection. Create the empty database first using your PostgreSQL administration tool. Percent-encode special characters in connection credentials. Generate the JWT signing key directly into the file without printing it:

   ```powershell
   .\.venv\Scripts\python.exe -c "import secrets; from dotenv import set_key; set_key('.env', 'JWT_SECRET_KEY', secrets.token_urlsafe(48))"
   ```

   Keep `JWT_ALGORITHM=HS256`. Set `OLLAMA_HOST`, `OLLAMA_MODEL` (default `qwen3:8b`) and `OLLAMA_TIMEOUT` as needed. A smaller installed model can be selected without code changes. Thinking is disabled and output is bounded. Do not commit `.env`.

3. Configure the **dedicated Entra test account** before enabling password workflows. Complete its MFA/security-information registration and SSPR setup in the tenant. Configure a single-page Entra app with the SPA redirect URI used by the frontend and delegated `User-PasswordProfile.ReadWrite.All` permission (admin consent required). Configure a separate confidential app registration with Microsoft Graph application `User.Read.All` permission and admin consent for SSPR completion verification. Set `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_GRAPH_CLIENT_ID`, `ENTRA_GRAPH_CLIENT_SECRET`, and `ENTRA_TEST_ACCOUNT_UPN`. The local AutoDeskAI test account must use the same email/UPN. Password reset redirects the user to Microsoft's SSPR page; the app marks it complete only after Graph reports a password-change timestamp newer than the request.

   Create a dedicated **Jira test account and project**. Create a Jira API token for an account authorized to administer project roles. Set `JIRA_BASE_URL` (HTTPS), `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`, `JIRA_TEST_ACCOUNT_EMAIL`, and that test user's `JIRA_TEST_ACCOUNT_ID`. The local AutoDeskAI account requesting access must match `JIRA_TEST_ACCOUNT_EMAIL`; Jira's user API must return the same email for the configured account ID. The project must define roles named `Users`, `Developers`, and `Administrators`; these map to Jira User, Developer, and Project Admin. Use credentials from test-only app registrations/accounts and keep them only in ignored environment files.

4. Start PostgreSQL using your local installation/service. Start Ollama if it is not already running, and install the configured model if necessary:

   ```powershell
   ollama serve
   # In another terminal, if the model is not installed:
   ollama pull qwen3:8b
   ```

5. Start the backend:

   ```powershell
   .\.venv\Scripts\python.exe check_services.py
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

6. Start the frontend in a separate terminal:

   ```powershell
   cd frontend
   npm.cmd ci
   npm.cmd run dev
   ```

   Open **http://127.0.0.1:5173/**. Vite proxies `/api` to the local backend. API documentation: **http://127.0.0.1:8000/docs**. JWTs stay in browser memory; reloading signs out. The prototype binds to loopback. A production deployment needs HTTPS and a same-origin reverse proxy for `/api`.

7. Register the dedicated test employee account (using the configured Entra/Jira test email) and an administrator through the UI. New accounts always receive the employee role. In a trusted local terminal, promote the intended administrator:

   ```powershell
   .\.venv\Scripts\python.exe -m app.manage promote-admin YOUR_ADMIN_EMAIL
   ```

   Log in to that account and open **Admin**. Enroll a Windows device with the test employee as owner. Save the one-time agent token privately in the endpoint's ignored `.env`; only its SHA-256 digest is stored by the backend. Set `SERVER_URL`, `DEVICE_ID`, `AGENT_TOKEN`, and `AGENT_SIMULATION_MODE=false` (the default). Chrome installation uses machine scope and requires the endpoint agent to run with the required local administrator privileges. The UI masks the token; select/copy it into the local environment file and dismiss it.

8. Start the endpoint agent from the repository directory:

   ```powershell
   .\.venv\Scripts\python.exe -m endpoint_agent.agent
   # A single heartbeat/task cycle:
   .\.venv\Scripts\python.exe -m endpoint_agent.agent --once
   ```

   Wait for its first heartbeat before submitting an installation. Admins can disable devices; disabled device tokens are rejected. Non-loopback agent connections require HTTPS. Installs use the fixed `Microsoft.VisualStudioCode` and `Google.Chrome` winget package IDs and verify the installed executable before completion. Set `AGENT_SIMULATION_MODE=true` only for a no-change development run.

## Demonstrate the three workflows

- Sign in as the dedicated test account and submit **I forgot my password.** Start Microsoft's hosted recovery, complete the tenant's MFA/SSPR checks, return to AutoDeskAI, and verify. The app confirms the change through Microsoft Graph without receiving the new password.
- Submit **Change my password**, sign into the dedicated Entra test account in the Microsoft popup, and enter its current and new passwords in the dedicated form. The values go only to Microsoft Graph and are never sent to Ollama or stored in AutoDeskAI.
- Select your enrolled Windows test device and submit **Install VS Code** or **Install Chrome**. Leave the endpoint agent running; the UI polls status and displays the agent's install verification.
- Submit **Give me developer access to Jira.** The server verifies the configured test account and Jira project role. Try **Project Admin** to see the administrator approval step before provisioning.

For a read-only connectivity check, with the backend already running:

```powershell
.\.venv\Scripts\python.exe demo_e2e.py
```

To explicitly run a live smoke test, first configure the dedicated test employee account, enrolled device, Jira test project, and real install mode, then run:

```powershell
.\.venv\Scripts\python.exe demo_e2e.py --execute
```

The script prompts for the test account's AutoDeskAI login without echoing its password, then installs/verifies VS Code and provisions/verifies the Jira Developer role. It never creates users or devices, and it does not handle Entra passwords; SSPR/password change remain interactive Microsoft flows.

## Tests and build

```powershell
.\.venv\Scripts\python.exe -m pytest test.py -q
# Or the existing unittest entry point:
.\.venv\Scripts\python.exe -m unittest test -v
cd frontend
npm.cmd run build
```

Automated tests use an isolated in-memory SQLite database and mocked model responses; they never modify your PostgreSQL users or need a running model. The live demo separately exercises PostgreSQL and Ollama.

## API map

| Area | Endpoints |
| --- | --- |
| Authentication | `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `GET /auth/entra/config` |
| Requests | `POST /requests` (alias `POST /ai/request`), `GET /requests`, `GET /requests/{id}`, `GET /requests/{id}/history` |
| Password operations | `POST /requests/{id}/password/reset/start`, `POST /requests/{id}/password/reset/verify`, `POST /requests/{id}/password/change` |
| Employee devices/catalog | `GET /devices`, `GET /catalog` |
| Agent | `POST /agent/register` (admin only), `GET /agent/heartbeat`, `GET /agent/tasks`, `POST /agent/tasks/{id}/result` |
| Admin views | `GET /admin/users`, `GET /admin/requests`, `GET /admin/devices`, `GET /admin/audit` |
| Admin changes | `PUT /admin/software/{key}`, `PUT /admin/applications/{key}`, `PATCH /admin/devices/{id}`, `POST /admin/requests/{id}/approval` |
| Legacy user routes | `GET/POST /users`, `PUT/DELETE /users/{id}`, now admin-only; creation requires a password; deletion refuses retained history |
| Health | `GET /`, `GET /db-test` (admin only) |

Use the Swagger **Authorize** button with the access token from login. User and device tokens are distinct. Request creation requires a client-generated `idempotency_key`; reuse that key after a network failure. New intentional requests need new keys. A clarification reply supplies the previous owned request's `previous_request_id`.

HTTP errors: 400 unsupported/unsafe action; 401 invalid/expired authentication; 403 role restriction; 404 absent or inaccessible resource; 409 duplicate/state conflict; 422 malformed input; 502/503 provider or AI/database failure. Validation errors omit submitted values to avoid echoing passwords.

## Database and execution boundaries

Startup validates the JWT configuration and adds missing tables with SQLAlchemy `create_all`. The existing `users` columns are preserved. New tables: `devices`, `helpdesk_requests`, `software_tasks`, `access_requests`, `audit_logs`, `software_policies`, `application_policies`. Startup also adds the nullable SSPR timestamp and Jira role field to older workflow tables without dropping data. Existing policy settings are preserved; the supported catalog is seeded only when absent. No destructive migration runs.

Request/task states include PENDING, PROCESSING, VERIFYING, AWAITING_APPROVAL, COMPLETED, FAILED, REJECTED, CANCELLED and NEEDS_CLARIFICATION. Users can cancel requests that have not started execution; dispatched or externally initiated work cannot be cancelled. Dispatch uses PostgreSQL row locks with SKIP LOCKED. Policies are rechecked before dispatch. Devices can report only their own dispatched tasks. Repeated identical result delivery is idempotent; conflicting or late results are rejected. The endpoint retries unacknowledged results during its current process lifetime. A crashed/lost task eventually fails after the configured timeout rather than silently succeeding. Frontend polling displays verified service completion to the requester.

Raw chat messages are not retained. Only recognized workflow tokens and canonical catalog names reach Ollama. Unknown entities are replaced with fixed unknown-target markers. This deliberately limits natural-language flexibility to reduce credential disclosure risk. The backend never displays arbitrary model prose as a success report. Audit details and endpoint result strings are backend-owned constants, not untrusted output.

## Operational limitations

- Password and Jira integrations are restricted to the explicitly configured test account and test project. The production tenant, test account, MFA/SSPR policy, Graph consent, Jira role names, API token, and project must be configured and verified before those actions are enabled.
- Password reset is completed by the user on Microsoft's SSPR page; AutoDeskAI verifies the Entra change timestamp and never handles the reset password. Password change uses delegated Graph permission and receives the current/new passwords transiently in backend memory. Use HTTPS outside localhost.
- Jira roles map only to the project's `Users`, `Developers`, and `Administrators` roles; Project Admin requires approval. Additional integrations must implement a separate provider and approved catalog mapping.
- Real installs require Windows Package Manager and the endpoint agent's local privileges; Chrome's machine-scope installation requires administrator rights. Only VS Code and Chrome have fixed package IDs.
- Frontend notifications are status updates shown by polling; no email/push delivery is configured.
- Tokens expire but there is no refresh-token or immediate user-session revocation flow. Device disabling is immediate. Public registration and administrator bootstrap are intended for local development.
- No production rate limiter, durable task queue, persistent endpoint result journal, or distributed scheduler is included. Task expiry is evaluated when requests/tasks/results are queried.
- Lists are bounded (200 employee requests, 500 admin records); full pagination is not implemented.
- Visual browser QA requires a connected browser. Build/HTTP verification is separate from visual verification.
