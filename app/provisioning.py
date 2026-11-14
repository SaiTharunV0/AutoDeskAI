"""Provider boundary for simulated and verified external grants."""
import json
from dataclasses import dataclass

@dataclass(frozen=True)
class ProvisioningResult:
    status: str
    simulated: bool
    verified: bool
    detail: str
    managed: bool = False

class MockProvider:
    supported_operations = frozenset({'simulate_grant'})

    def provision(self, policy, access):
        if access.application != policy.key or access.requested_role not in json.loads(policy.requestable_roles_json):
            return ProvisioningResult('NOT_CONFIGURED', False, False, 'Target or role does not match the catalog')
        return ProvisioningResult('SIMULATED', True, False, 'No external grant was made')

class NoProvider:
    supported_operations = frozenset()

    def provision(self, policy, access):
        return ProvisioningResult('NOT_CONFIGURED', False, False, 'No provider is configured')

class GitHubProvider:
    def provision(self, policy, access):
        from app.github_provider import GitHubOrganizationProvider
        result = GitHubOrganizationProvider().provision(access)
        return ProvisioningResult(result.status, False, result.verified,
                                  'GitHub membership state checked', result.managed)

PROVIDERS = {'MOCK': MockProvider(), 'NONE': NoProvider(), 'GITHUB_ORG': GitHubProvider()}

def provision(policy, access):
    return PROVIDERS.get(policy.provider_type, NoProvider()).provision(policy, access)
