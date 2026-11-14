"""Bounded GitHub organization membership operations for verified local identities."""
import os
import re
from dataclasses import dataclass
import httpx

_ORG = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$')

@dataclass(frozen=True)
class GitHubResult:
    status: str
    verified: bool = False
    managed: bool = False

class GitHubOrganizationProvider:
    def __init__(self, *, org=None, token=None, transport=None):
        self.org = org if org is not None else os.getenv('GITHUB_ORG', '')
        self.token = token if token is not None else os.getenv('GITHUB_TOKEN', '')
        self.transport = transport

    def _client(self):
        return httpx.Client(base_url='https://api.github.com', transport=self.transport,
            timeout=10, follow_redirects=False, headers={
                'Authorization': 'Bearer ' + self.token,
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'AutoDeskAI-access-provider',
            })

    def _check(self, client, access):
        user = client.get(f'/users/{access.github_login}')
        if user.status_code == 404:
            return GitHubResult('IDENTITY_MISMATCH')
        if user.status_code != 200:
            return GitHubResult('FAILED')
        if user.json().get('id') != access.github_user_id:
            return GitHubResult('IDENTITY_MISMATCH')
        membership = client.get(f'/orgs/{self.org}/memberships/{access.github_login}')
        if membership.status_code == 200:
            state = membership.json().get('state')
            if state == 'active':
                return GitHubResult('GRANTED', True, bool(access.provider_managed))
            if state == 'pending':
                return GitHubResult('PENDING_ACCEPTANCE', False, bool(access.provider_managed))
        if membership.status_code == 404:
            # GitHub may hide a membership from a token without permissions.
            permission = client.get(f'/orgs/{self.org}/invitations', params={'per_page': 1})
            if permission.status_code == 200:
                return GitHubResult('ABSENT')
        return GitHubResult('FAILED')

    def _configured(self, access):
        return (bool(self.token and self.org and _ORG.fullmatch(self.org))
                and access.github_login and _ORG.fullmatch(access.github_login)
                and isinstance(access.github_user_id, int)
                and access.provider_resource == self.org
                and access.requested_role == 'member')

    def verify(self, access):
        if not self._configured(access):
            return GitHubResult('NOT_CONFIGURED')
        try:
            with self._client() as client:
                result = self._check(client, access)
                return GitHubResult('NOT_GRANTED') if result.status == 'ABSENT' else result
        except (httpx.TimeoutException, httpx.TransportError, ValueError, KeyError):
            return GitHubResult('FAILED')

    def provision(self, access):
        if not self._configured(access):
            return GitHubResult('NOT_CONFIGURED')
        try:
            with self._client() as client:
                result = self._check(client, access)
                if result.status != 'ABSENT':
                    return result
                response = client.put(f'/orgs/{self.org}/memberships/{access.github_login}',
                                      json={'role': 'member'})
                if response.status_code != 200:
                    return GitHubResult('FAILED')
                state = response.json().get('state')
                if state == 'pending':
                    return GitHubResult('PENDING_ACCEPTANCE', False, True)
                if state == 'active':
                    checked = self._check(client, access)
                    return GitHubResult('GRANTED', True, True) if checked.verified else GitHubResult('FAILED')
                return GitHubResult('FAILED')
        except (httpx.TimeoutException, httpx.TransportError, ValueError, KeyError):
            return GitHubResult('FAILED')
