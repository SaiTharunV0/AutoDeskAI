"""Application access provider interface and registry."""
from typing import Protocol


class AccessService(Protocol):
    def provision(self, role_key: str) -> bool: ...


class AccessIntegrationError(RuntimeError):
    pass


def get_access_service(application: str) -> AccessService:
    if application == "jira":
        from services.jira import JiraAccessService
        return JiraAccessService()
    raise AccessIntegrationError("Application access provider is not configured.")
