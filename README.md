# AutoDeskAI

Authenticated IT helpdesk prototype using FastAPI, SQLAlchemy/PostgreSQL, React/Vite and local Ollama. The AI classifies requests; backend policy and device ownership determine what can run.

## Recent changes

This implementation preserves the existing backend foundation while completing the local helpdesk workflow, security controls, and agent/device integration. Key updates include:

- Configurable Ollama-based classification with bounded structured outputs, prompt constraints, clarification handling, and validation before actions are dispatched.
- Stronger authentication and authorization, including PBKDF2 password hashing, legacy bcrypt compatibility, expiring JWTs, server-side admin checks, and protected employee/admin APIs.
- PostgreSQL-backed request lifecycle, device ownership checks, audit history, policy enforcement, idempotent submissions, and task tracking with safe retry behavior.
- Endpoint-agent enrollment and task execution with device identity validation, local allowlist checks, simulating install results, and result idempotency protections.
- React/Vite frontend for registration, login, device enrollment, request submission, policy review, admin dashboard, and status polling.
- End-to-end demo and verification scripts for local PostgreSQL/Ollama validation without modifying production credentials.

## What works

- Employee registration, password hashing (PBKDF2-SHA256; existing bcrypt hashes supported), expiring JWTs and server-side employee/admin authorization.
- Password reset/change requests with an explicit authenticated confirmation step and a **simulated** identity operation. Actual login passwords do not change.
- Approved VS Code installation tasks dispatched only to the enrolled device. The endpoint agent validates its device identity and local software allowlist, simulates installation and reports a confirmed result.
- Tableau access decisions from the backend policy table. This is a **demo access decision**, not external provisioning.
- Request status/history, idempotent submissions, device heartbeat/offline checks, task timeout, audit records, and admin policy/device management.
- React login/registration, employee dashboard, helpdesk, device selection, request history, profile and admin workspace.

No Gemini dependency or API call remains. Neither model output nor API input is passed to a command runner. There is no shell execution capability in the endpoint agent.

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

3. Start PostgreSQL using your local installation/service. Start Ollama if it is not already running, and install the configured model if necessary:

   ```powershell
   ollama serve
   # In another terminal, if the model is not installed:
   ollama pull qwen3:8b
   ```

4. Start the backend:

   ```powershell
   .\.venv\Scripts\python.exe check_services.py
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

5. Start the frontend in a separate terminal:

   ```powershell
   cd frontend
   npm.cmd ci
   npm.cmd run dev
   ```

   Open **http://127.0.0.1:5173/**. Vite proxies `/api` to the local backend. API documentation: **http://127.0.0.1:8000/docs**. JWTs stay in browser memory; reloading signs out. The prototype binds to loopback. A production deployment needs HTTPS and a same-origin reverse proxy for `/api`.

6. Register your employee and administrator accounts through the UI. New accounts always receive the employee role. In a trusted local terminal, promote the intended administrator:

   ```powershell
   .\.venv\Scripts\python.exe -m app.manage promote-admin YOUR_ADMIN_EMAIL
   ```

   Log in to that account and open **Admin**. Enroll a device with the employee as owner. Save the one-time agent token privately in the endpoint's ignored `.env`; only its SHA-256 digest is stored by the backend. Set `SERVER_URL`, `DEVICE_ID`, `AGENT_TOKEN`, and `AGENT_SIMULATION_MODE=true`. The UI masks the token; select/copy it into the local environment file and dismiss it.

7. Start the endpoint agent from the repository directory:

   ```powershell
   .\.venv\Scripts\python.exe -m endpoint_agent.agent
   # A single heartbeat/task cycle:
   .\.venv\Scripts\python.exe -m endpoint_agent.agent --once
   ```

   Wait for its first heartbeat before submitting an installation. Admins can disable devices; disabled device tokens are rejected. Non-loopback agent connections require HTTPS. Real installation mode intentionally fails closed.

## Demonstrate the three workflows

- Sign in and submit **I forgot my password.** Confirm the simulated operation on its request card. The request and audit history show completion without changing your login password.
- Select your enrolled device and submit **Install VS Code.** Leave the endpoint agent running. The UI polls status every five seconds and shows the endpoint-confirmed simulation result.
- Submit **I need access to Tableau.** The policy table determines approval or rejection. Disable Tableau or require the admin role to demonstrate rejection.

For a repeatable live integration check, with the backend already running:

```powershell
.\.venv\Scripts\python.exe demo_e2e.py
```

This uses actual Ollama classification, PostgreSQL records and the endpoint-agent module. It creates uniquely named demo employee/admin accounts, a device and three requests. Generated credentials remain in process memory and are never printed or committed. Demo records are retained as verification history. The script checks database records, audits, Swagger, unauthenticated denial, RBAC and command rejection.

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
| Authentication | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Requests | `POST /requests` (alias `POST /ai/request`), `GET /requests`, `GET /requests/{id}`, `GET /requests/{id}/history` |
| Password simulation | `POST /requests/{id}/password/confirm` |
| Employee devices/catalog | `GET /devices`, `GET /catalog` |
| Agent | `POST /agent/register` (admin only), `GET /agent/heartbeat`, `GET /agent/tasks`, `POST /agent/tasks/{id}/result` |
| Admin views | `GET /admin/users`, `GET /admin/requests`, `GET /admin/devices`, `GET /admin/audit` |
| Admin changes | `PUT /admin/software/{key}`, `PUT /admin/applications/{key}`, `PATCH /admin/devices/{id}` |
| Legacy user routes | `GET/POST /users`, `PUT/DELETE /users/{id}`, now admin-only; creation requires a password; deletion refuses retained history |
| Health | `GET /`, `GET /db-test` (admin only) |

Use the Swagger **Authorize** button with the access token from login. User and device tokens are distinct. Request creation requires a client-generated `idempotency_key`; reuse that key after a network failure. New intentional requests need new keys. A clarification reply supplies the previous owned request's `previous_request_id`.

HTTP errors: 400 unsupported/unsafe action; 401 invalid/expired authentication; 403 role restriction; 404 absent or inaccessible resource; 409 duplicate/state conflict; 422 malformed input; 503 AI/database unavailable. Validation errors omit submitted values to avoid echoing passwords.

## Database and execution boundaries

Startup validates the JWT configuration and adds missing tables with SQLAlchemy `create_all`. The existing `users` columns are preserved. New tables: `devices`, `helpdesk_requests`, `software_tasks`, `access_requests`, `audit_logs`, `software_policies`, `application_policies`. Existing policy settings are preserved; the demo catalog is seeded only when absent. No destructive migration runs. For future changes to existing columns, use explicit versioned migrations; `create_all` does not alter old schemas.

Request/task states include PENDING, PROCESSING, COMPLETED, FAILED, REJECTED and NEEDS_CLARIFICATION. Dispatch uses PostgreSQL row locks with SKIP LOCKED. Policies are rechecked before dispatch. Devices can report only their own dispatched tasks. Repeated identical result delivery is idempotent; conflicting or late results are rejected. The endpoint retries unacknowledged results during its current process lifetime. A crashed/lost task eventually fails after the configured timeout rather than silently succeeding.

Raw chat messages are not retained. Only recognized workflow tokens and canonical catalog names reach Ollama. Unknown entities are replaced with fixed unknown-target markers. This deliberately limits natural-language flexibility to reduce credential disclosure risk. The backend never displays arbitrary model prose as a success report. Audit details and endpoint result strings are backend-owned constants, not untrusted output.

## Prototype limitations

- Password, access provisioning and installation are explicit simulations. Only VS Code and Tableau are predefined capabilities. Adding a capability requires a code-reviewed catalog/installer change; administrators can toggle existing approvals and access roles.
- An authenticated password-reset request does not provide unauthenticated account recovery. Real identity integration needs an approved identity-provider verification flow.
- Tokens expire but there is no refresh-token or immediate user-session revocation flow. Device disabling is immediate. Public registration and administrator bootstrap are intended for local development.
- No production rate limiter, durable task queue, persistent endpoint result journal, distributed scheduler, or external identity/access connector is included. Task expiry is evaluated when requests/tasks/results are queried.
- Lists are bounded (200 employee requests, 500 admin records); full pagination is not implemented.
- Visual browser QA requires a connected browser. Build/HTTP verification is separate from visual verification.
