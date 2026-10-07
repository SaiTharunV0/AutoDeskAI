"""Password operations are isolated from request orchestration and persistence."""
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx

import config

GRAPH_URL = "https://graph.microsoft.com/v1.0"


class PasswordService(Protocol):
    def reset_url(self) -> str: ...
    def verify_reset(self, started_at: datetime) -> bool: ...
    def change_password(self, access_token: str, current_password: str, new_password: str) -> None: ...


class PasswordIntegrationError(RuntimeError):
    pass


class EntraPasswordService:
    def reset_url(self) -> str:
        if not config.ENTRA_TEST_ACCOUNT_UPN:
            raise PasswordIntegrationError("Entra test account is not configured.")
        self._ensure_graph_configuration()
        parsed = urlparse(config.ENTRA_SSPR_URL)
        if parsed.scheme != "https" or parsed.hostname != "passwordreset.microsoftonline.com":
            raise PasswordIntegrationError("Configure Microsoft's official Entra SSPR URL.")
        return config.ENTRA_SSPR_URL

    @staticmethod
    def _ensure_graph_configuration() -> None:
        required = (config.ENTRA_TENANT_ID, config.ENTRA_GRAPH_CLIENT_ID,
                    config.ENTRA_GRAPH_CLIENT_SECRET, config.ENTRA_TEST_ACCOUNT_UPN)
        if not all(required):
            raise PasswordIntegrationError("Entra password verification is not configured.")

    def _graph_token(self) -> str:
        self._ensure_graph_configuration()
        try:
            response = httpx.post(
                f"https://login.microsoftonline.com/{quote(config.ENTRA_TENANT_ID, safe='')}/oauth2/v2.0/token",
                data={
                    "client_id": config.ENTRA_GRAPH_CLIENT_ID,
                    "client_secret": config.ENTRA_GRAPH_CLIENT_SECRET,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
                timeout=15,
            )
            response.raise_for_status()
            token = response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise PasswordIntegrationError("Entra did not issue an access token.")
            return token
        except httpx.HTTPError:
            raise PasswordIntegrationError("Unable to authenticate with Microsoft Entra ID.") from None
        except (ValueError, TypeError, AttributeError):
            raise PasswordIntegrationError("Microsoft Entra returned an invalid token response.") from None

    def verify_reset(self, started_at: datetime) -> bool:
        token = self._graph_token()
        upn = quote(config.ENTRA_TEST_ACCOUNT_UPN, safe="")
        try:
            response = httpx.get(
                f"{GRAPH_URL}/users/{upn}",
                params={"$select": "userPrincipalName,lastPasswordChangeDateTime"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            response.raise_for_status()
            identity = response.json()
            account = identity.get("userPrincipalName")
            if not isinstance(account, str) or account.strip().lower() != config.ENTRA_TEST_ACCOUNT_UPN:
                raise PasswordIntegrationError("Entra returned a different account than the configured test user.")
            changed = identity.get("lastPasswordChangeDateTime")
        except httpx.HTTPError:
            raise PasswordIntegrationError("Unable to verify the Entra password reset.") from None
        except (ValueError, TypeError, AttributeError):
            raise PasswordIntegrationError("Microsoft Entra returned an invalid user response.") from None
        if not isinstance(changed, str):
            raise PasswordIntegrationError("Entra password-change verification is unavailable.")
        try:
            changed_at = datetime.fromisoformat(changed.replace("Z", "+00:00"))
        except ValueError:
            raise PasswordIntegrationError("Entra returned an invalid password-change timestamp.") from None
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        if changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=timezone.utc)
        return changed_at > started_at

    def change_password(self, access_token: str, current_password: str, new_password: str) -> None:
        if not config.ENTRA_TEST_ACCOUNT_UPN or not access_token:
            raise PasswordIntegrationError("Entra password change is not configured.")
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            identity = httpx.get(
                f"{GRAPH_URL}/me",
                params={"$select": "userPrincipalName"},
                headers=headers,
                timeout=15,
            )
            identity.raise_for_status()
            if (identity.json().get("userPrincipalName", "").strip().lower()
                    != config.ENTRA_TEST_ACCOUNT_UPN):
                raise PermissionError("Sign in with the configured Entra test account.")
            response = httpx.post(
                f"{GRAPH_URL}/me/changePassword",
                headers=headers,
                json={"currentPassword": current_password, "newPassword": new_password},
                timeout=20,
            )
            response.raise_for_status()
            if response.status_code != 204:
                raise PasswordIntegrationError("Microsoft Entra did not confirm the password change.")
        except PermissionError:
            raise
        except httpx.HTTPError:
            raise PasswordIntegrationError("Microsoft Entra rejected or could not complete the password change.") from None
        except (ValueError, TypeError, AttributeError):
            raise PasswordIntegrationError("Microsoft Entra returned an invalid identity response.") from None


def get_password_service() -> PasswordService:
    return EntraPasswordService()
