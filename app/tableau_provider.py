"""Tableau Cloud site access, bounded to administrator approved users."""
import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


_SITE = re.compile(r'^[A-Za-z0-9_-]{1,80}$')
_ROLES = frozenset({'Viewer', 'Explorer', 'ExplorerCanPublish', 'Creator'})
_VERSION = '3.29'


@dataclass(frozen=True)
class TableauResult:
    status: str
    verified: bool = False
    managed: bool = False


class TableauCloudProvider:
    def __init__(self, *, host=None, site=None, pat_name=None, pat_secret=None,
                 role_map=None, transport=None):
        self.host = host if host is not None else os.getenv('TABLEAU_HOST', '')
        self.site = site if site is not None else os.getenv('TABLEAU_SITE_CONTENT_URL', '')
        self.pat_name = pat_name if pat_name is not None else os.getenv('TABLEAU_PAT_NAME', '')
        self.pat_secret = pat_secret if pat_secret is not None else os.getenv('TABLEAU_PAT_SECRET', '')
        self.role_map = role_map if role_map is not None else os.getenv('TABLEAU_ROLE_MAP', '')
        self.transport = transport

    def _configured(self, policy, access):
        try:
            url = urlsplit(self.host)
            roles = json.loads(self.role_map)
            allowed = json.loads(policy.requestable_roles_json)
            port = url.port
        except (ValueError, TypeError):
            return False
        return (url.scheme == 'https' and url.hostname is not None
                and url.hostname.endswith('.online.tableau.com')
                and not url.username and not url.password and not port
                and not url.path.strip('/') and not url.query and not url.fragment
                and bool(self.site and _SITE.fullmatch(self.site))
                and bool(self.pat_name and self.pat_secret)
                and isinstance(roles, dict) and roles
                and all(isinstance(k, str) and k in allowed
                        and isinstance(v, str) and v in _ROLES
                        for k, v in roles.items())
                and access.application == 'tableau'
                and access.requested_role in roles
                and access.provider_resource == self.site)

    def provision(self, policy, access):
        if not self._configured(policy, access):
            return TableauResult('NOT_CONFIGURED')
        email = access.request.user.email.strip().lower()
        if not email or '@' not in email:
            return TableauResult('IDENTITY_MISMATCH')
        role = json.loads(self.role_map)[access.requested_role]
        try:
            with httpx.Client(base_url=self.host, transport=self.transport, timeout=10,
                              follow_redirects=False) as client:
                signin = client.post(f'/api/{_VERSION}/auth/signin', json={'credentials': {
                    'personalAccessTokenName': self.pat_name,
                    'personalAccessTokenSecret': self.pat_secret,
                    'site': {'contentUrl': self.site}}})
                if signin.status_code != 200:
                    return TableauResult('FAILED')
                credentials = signin.json().get('credentials', {})
                token = credentials.get('token')
                site_id = credentials.get('site', {}).get('id')
                if not token or not site_id or credentials['site'].get('contentUrl') != self.site:
                    return TableauResult('FAILED')
                headers = {'X-Tableau-Auth': token, 'Accept': 'application/json'}
                path = f'/api/{_VERSION}/sites/{site_id}/users'
                users = client.get(path, params={'filter': f'name:eq:{email}'}, headers=headers)
                if users.status_code != 200:
                    return TableauResult('FAILED')
                found = [row for row in users.json().get('users', {}).get('user', [])
                         if row.get('name', '').lower() == email]
                if len(found) > 1:
                    return TableauResult('IDENTITY_MISMATCH')
                managed = False
                if found:
                    user_id = found[0].get('id')
                    if found[0].get('siteRole') != role:
                        return TableauResult('ROLE_MISMATCH')
                else:
                    created = client.post(path, json={'user': {'name': email, 'siteRole': role}}, headers=headers)
                    if created.status_code != 201:
                        return TableauResult('FAILED')
                    user_id = created.json().get('user', {}).get('id')
                    managed = True
                if not user_id:
                    return TableauResult('FAILED')
                checked = client.get(f'{path}/{user_id}', headers=headers)
                if checked.status_code != 200:
                    return TableauResult('FAILED', managed=managed)
                user = checked.json().get('user', {})
                if user.get('id') != user_id or user.get('name', '').lower() != email:
                    return TableauResult('IDENTITY_MISMATCH', managed=managed)
                if user.get('siteRole') != role:
                    return TableauResult('ROLE_MISMATCH', managed=managed)
                return TableauResult('GRANTED', True, managed)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return TableauResult('FAILED')
