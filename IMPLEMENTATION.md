# Service implementation and validation

## Implemented services

- **Password change:** a dedicated Entra test account signs in through MSAL; FastAPI confirms the Graph `/me` identity and calls the delegated `/me/changePassword` API. Password values are submitted outside chat, held only in memory, and excluded from request/audit records.
- **Password reset:** AutoDeskAI starts Microsoft's hosted SSPR page. The user completes the tenant's MFA/recovery flow there; FastAPI verifies the dedicated account's Entra `lastPasswordChangeDateTime` before completing the request.
- **Software installation:** registered Windows agents run fixed winget package IDs for VS Code or Chrome, then verify the expected executable before reporting completion. Real mode is the default; simulation is an explicit development option.
- **Jira access:** the configured Jira test account and test project are checked through Jira REST. Only the `Users`, `Developers`, and `Administrators` project roles are supported. Project Admin remains pending until an administrator approves it; the provider verifies the role after provisioning.
- **Common workflow:** sanitized Ollama intent/role extraction, backend policy and account eligibility, idempotent helpdesk tickets, status transitions, audit events, and frontend status polling/approval actions.

## Integration configuration and safety

Entra Graph IDs/secrets, SSPR test UPN, Jira API credentials, project key, test-account email/account ID, and endpoint-agent credentials are environment configuration only. Entra and Jira actions reject requests outside their configured dedicated test identities. Provider errors do not create success-shaped results. Jira and Graph secrets and password values are not written to PostgreSQL or audit details.

The workflow schema update is additive: older databases gain `helpdesk_requests.password_started_at` and `access_requests.requested_role` without dropping existing user or request data. Existing policy rows are preserved.

## Validation run

- `pytest test.py -q`: **26 passed**. Provider HTTP calls and model classification are mocked; tests cover account matching, role allowlisting, SSPR verification, request ownership, approvals, and password/audit separation.
- `npm run build`: **passed**; MSAL is dynamically split from the main UI bundle.
- Production dependency audit (`npm audit --omit=dev`): **0 vulnerabilities**.
- Python Problems check: no errors in the changed Python files.
- No live Entra/Jira mutation or endpoint installation was run during validation. `demo_e2e.py` defaults to a read-only connectivity check; `--execute` explicitly triggers real VS Code installation and Jira role provisioning against the configured test accounts.

## Operational boundaries

Use Microsoft's hosted SSPR for resets; AutoDeskAI does not collect reset passwords. Password changes require the delegated Graph permission and an HTTPS deployment outside localhost. Jira needs project-role administration permission and must expose the configured dedicated test account's email for account verification. Chrome machine-scope installation requires endpoint administrator privileges. The UI currently provides in-app status polling rather than email/push notifications.

The service remains intentionally limited to two Windows packages and one Jira project. Additional identity providers, applications, and roles require explicit provider and catalog additions. Durable task queues, persistent agent result journals, production rate limiting, and full list pagination are not included.
