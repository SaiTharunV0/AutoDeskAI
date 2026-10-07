"""Jira project-role provisioning with a fixed, predefined role catalog."""
from urllib.parse import quote, urlparse

import httpx

import config
from app.catalog import ACCESS_ROLES
from services.access import AccessIntegrationError

API_ROOT = "/rest/api/3"


class JiraIntegrationError(AccessIntegrationError):
    pass


class JiraAccessService:
    def _configuration(self) -> tuple[str, tuple[str, str], str, str]:
        if not all((config.JIRA_BASE_URL, config.JIRA_EMAIL, config.JIRA_API_TOKEN,
                    config.JIRA_PROJECT_KEY, config.JIRA_TEST_ACCOUNT_EMAIL,
                    config.JIRA_TEST_ACCOUNT_ID)):
            raise JiraIntegrationError("Jira test-project integration is not configured.")
        parsed = urlparse(config.JIRA_BASE_URL)
        if parsed.scheme != "https" or not parsed.netloc:
            raise JiraIntegrationError("Jira must be configured with an HTTPS URL.")
        return (
            config.JIRA_BASE_URL,
            (config.JIRA_EMAIL, config.JIRA_API_TOKEN),
            config.JIRA_PROJECT_KEY,
            config.JIRA_TEST_ACCOUNT_ID,
        )

    def provision(self, role_key: str) -> bool:
        role = ACCESS_ROLES.get(role_key)
        if not role:
            raise JiraIntegrationError("Requested Jira role is not in the approved catalog.")
        base_url, auth, project, account_id = self._configuration()
        project_path = quote(project, safe="")
        headers = {"Accept": "application/json"}
        try:
            with httpx.Client(base_url=base_url, auth=auth, headers=headers, timeout=20) as client:
                identity = client.get(f"{API_ROOT}/user", params={"accountId": account_id})
                identity.raise_for_status()
                identity_data = identity.json()
                account_email = identity_data.get("emailAddress")
                if (identity_data.get("accountId") != account_id or
                        not isinstance(account_email, str) or
                        account_email.strip().lower() != config.JIRA_TEST_ACCOUNT_EMAIL):
                    raise JiraIntegrationError("Configured Jira account does not match the dedicated test account.")
                roles_response = client.get(f"{API_ROOT}/project/{project_path}/role")
                roles_response.raise_for_status()
                role_urls = roles_response.json()
                role_url = role_urls.get(role["jira_role"])
                if not isinstance(role_url, str):
                    raise JiraIntegrationError("The configured Jira project does not define the approved role.")
                role_id = role_url.rstrip("/").rsplit("/", 1)[-1]
                if not role_id.isdigit():
                    raise JiraIntegrationError("Jira returned an invalid project-role identifier.")
                role_path = f"{API_ROOT}/project/{project_path}/role/{role_id}"
                current = client.get(role_path)
                current.raise_for_status()
                actors = current.json().get("actors", [])
                if self._contains_account(actors, account_id):
                    return True
                added = client.post(role_path, json={"user": [account_id]})
                added.raise_for_status()
                verified = client.get(role_path)
                verified.raise_for_status()
                return self._contains_account(verified.json().get("actors", []), account_id)
        except JiraIntegrationError:
            raise
        except httpx.HTTPError:
            raise JiraIntegrationError("Jira provisioning or role verification failed.") from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise JiraIntegrationError("Jira returned an invalid project-role response.") from None

    @staticmethod
    def _contains_account(actors: list, account_id: str) -> bool:
        for actor in actors:
            if not isinstance(actor, dict):
                continue
            user = actor.get("actorUser") or actor.get("user") or {}
            if isinstance(user, dict) and user.get("accountId") == account_id:
                return True
        return False
