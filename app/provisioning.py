"""Provider boundary. Neither built-in provider can grant external permissions."""
import json
from dataclasses import dataclass

@dataclass(frozen=True)
class ProvisioningResult:
    status: str
    simulated: bool
    verified: bool
    detail: str

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

PROVIDERS = {'MOCK': MockProvider(), 'NONE': NoProvider()}

def provision(policy, access):
    return PROVIDERS.get(policy.provider_type, NoProvider()).provision(policy, access)
