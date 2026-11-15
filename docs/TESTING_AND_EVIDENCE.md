# AutoDeskAI testing results and implementation evidence

**Recorded:** 16 November 2026. **Scope:** Local repository checks and evidence available in source. Results below distinguish checks run in this session, source-level evidence, and reported live behavior. No live Jira or GitHub grant was performed for this document.

## 1. Test results

| Check | Result | Evidence and boundary |
| --- | --- | --- |
| Frontend unit tests | **Passed: 35/35** | `npm.cmd test` in `frontend/`, Node test runner, 0 failures in this session. Covers API client behavior, access form and policy logic, chat, polling, password destination checks, gesture handling, and request outcomes. |
| Frontend production build | **Passed** | `npm.cmd run build` in `frontend/`; Vite 7.3.6 transformed 1,592 modules and wrote `dist/` in this session. This verifies compilation, not a Vercel deploy. |
| Backend automated tests | **Not run in this session** | `test.py` contains 82 `test_` methods by source count. The session's Python environment configuration and VS Code test tools returned an unsupported tool error. A source count is not a pass count. |
| Jira invitation and group grant | **Mocked tests in source; live verification pending** | [`test.py`](../test.py) exercises provider behavior with `httpx.MockTransport`. The invitation code and retry path require a deployed build and a dedicated Atlassian account test. |
| GitHub membership and expiry | **Mocked tests in source; live verification pending** | Backend tests exercise member invitation/verification and revocation decisions with mocks. The expiry cron's deployment and credentials must be checked separately. |
| Visual Studio Code installation | **Owner reported one successful end-to-end installation** | The README records a device enrollment, task delivery, WinGet installation, and package verification on an employee Windows device. The newer agent auto-stop bundle was not part of that reported test. No machine log or screenshot was added to this repository for this document. |
| Windows agent packaging | **Workflow configured; current run not checked** | [`.github/workflows/endpoint-agent.yml`](../.github/workflows/endpoint-agent.yml) builds a standalone Windows executable, checks `--help`, and uploads a bundle artifact. Configuration alone is not evidence that a particular run succeeded. |

The frontend checks above were run against the local checkout. At documentation time, the branch was ahead of `origin/main`; a successful local build does not establish the running Render/Vercel revision.

## 2. Reproduction commands

Install development dependencies first using the instructions in [`README.md`](../README.md). These commands do not trigger a live software installation:

```powershell
# Repository root, in a configured Python virtual environment
.\.venv\Scripts\python.exe -m pytest test.py -q

# Frontend
Set-Location frontend
npm.cmd test
npm.cmd run build
```

CI runs the Python suite on Python 3.11 and the frontend suite/build on Node 22 for pull requests and pushes to `main` or `backend`; see [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). A CI configuration is an automated check definition, not a substitute for recording a successful run URL and commit hash.

## 3. Implementation traceability

| Requirement / behavior | Implementation evidence | Verification level |
| --- | --- | --- |
| Employee signup waits for admin authorization | [`app/main.py`](../app/main.py) registration and approval routes; [`auth.py`](../auth.py) request-time approval check; [`app/models.py`](../app/models.py) `User.approval_status` | Backend tests exist; current run unavailable |
| Admin rejects/deauthorizes and status persists | Admin approval route, `User` row, audit events, employee login status UI | Source and backend tests |
| Chat remains within supported helpdesk scope | [`agent.py`](../agent.py) sanitization/classification; [`app/workflows.py`](../app/workflows.py) ticket routing; [`app/chat_limits.py`](../app/chat_limits.py) DB-backed limits | Source, backend tests, frontend chat tests passed |
| Employee sees one admin decision message | [`app/access.py`](../app/access.py) notifications; [`frontend/src/chat_flow.js`](../frontend/src/chat_flow.js) and [`frontend/src/Notifications.jsx`](../frontend/src/Notifications.jsx) | Frontend tests passed; backend route tests exist |
| Password action goes to Microsoft without handling work password | [`app/main.py`](../app/main.py) password action and recovery URL; [`frontend/src/sspr.js`](../frontend/src/sspr.js) | Frontend destination tests passed; Microsoft outcome is not verified |
| Policy evaluation precedes an access grant | [`app/access.py`](../app/access.py) `evaluate`, decision and provisioning; [`app/models.py`](../app/models.py) access record and revision | Source and backend tests |
| GitHub identity and org membership verification | [`app/github_provider.py`](../app/github_provider.py), [`app/access.py`](../app/access.py), [`app/github_expiry.py`](../app/github_expiry.py) | Mocked tests; live tenant and cron state unverified |
| Jira invitation, group and product verification | [`app/jira_provider.py`](../app/jira_provider.py), [`app/access.py`](../app/access.py) | Mocked tests; live invite/group test pending |
| Software task belongs to connected employee device | [`app/main.py`](../app/main.py) `/software/requests`, `/agent/tasks`, task result routes; [`app/models.py`](../app/models.py) device ownership | Backend tests exist; owner reported successful earlier install |
| WinGet success requires installed-package verification | [`endpoint_agent/installer.py`](../endpoint_agent/installer.py); [`endpoint_agent/agent.py`](../endpoint_agent/agent.py) result reporting | Mocked tests; owner reported earlier live install |
| API contract is inspectable | FastAPI app in [`app/main.py`](../app/main.py) generates `/docs` and `/openapi.json` | Source; deployed endpoint not captured here |

## 4. Evidence needed for a final demonstration

The following artifacts should be captured from the exact deployed commit used for assessment. Record a timestamp and redact tokens, passwords, email addresses not intended for publication, and private URLs.

1. **Revision evidence:** Git commit hash plus Render backend and Vercel frontend deployment IDs for that hash. Confirm the frontend `/api` rewrite reaches the intended backend.
2. **Account flow:** Pending employee login screen, corresponding admin pending row, approval, and employee login success. Show a rejected/deauthorized account separately if required.
3. **Ticket flow:** A chat or catalog request with its ID, admin decision, employee notification, and request history. Show that an admin decision does not require employee completion confirmation.
4. **Jira live grant:** Dedicated test employee email, admin approved request and provisioning status, Atlassian group member row, and Jira product access. If `INVITED`, capture the invitation and repeat verification after acceptance. Use a dedicated account because a product seat may be billable.
5. **GitHub live grant:** Confirmed GitHub user ID/login, organization invitation, accepted membership, and `GRANTED` status. For expiry, capture the cron run and verified removal only for a test membership created by AutoDeskAI.
6. **Windows installation:** Device Connected state, queued/processing/completed task, WinGet exact package check, and agent exit after verified success with the updated bundle. Preserve only redacted agent output.
7. **Automated checks:** CI run link for the same commit showing backend, frontend, and Windows packaging jobs as applicable. The existing report figures are explanatory drawings and should not be presented as these screenshots.

## 5. Limits on conclusions

The 35 frontend test pass and successful build establish local UI logic and compilation only. Mocked backend tests can establish request and provider logic but do not prove real credentials, provider permissions, account visibility, billing behavior, or deployed revisions. The earlier successful Windows installation is an owner-reported observation; it does not verify the later auto-stop update. A `GRANTED` status should be cross-checked against the provider's member list and product role before it is used as final demonstration evidence.
