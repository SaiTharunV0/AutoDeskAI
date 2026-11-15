"""Jira Cloud group grant for an existing, identifiable site user."""
import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


_GROUP_ID = re.compile(r'^[A-Za-z0-9_-]{1,100}$')


@dataclass(frozen=True)
class JiraResult:
    status: str
    verified: bool = False
    managed: bool = False


class JiraCloudProvider:
    def __init__(self, *, site=None, admin_email=None, api_token=None,
                 role_map=None, product_key=None, transport=None):
        self.site = site if site is not None else os.getenv('JIRA_SITE_URL', '')
        self.admin_email = admin_email if admin_email is not None else os.getenv('JIRA_ADMIN_EMAIL', '')
        self.api_token = api_token if api_token is not None else os.getenv('JIRA_API_TOKEN', '')
        self.role_map = role_map if role_map is not None else os.getenv('JIRA_ROLE_MAP', '')
        self.product_key = product_key if product_key is not None else os.getenv('JIRA_PRODUCT_KEY', '')
        self.transport = transport

    def _configured(self, policy, access):
        try:
            url = urlsplit(self.site)
            mapping = json.loads(self.role_map)
            roles = json.loads(policy.requestable_roles_json)
            port = url.port
        except (ValueError, TypeError):
            return False
        return (url.scheme == 'https' and url.hostname is not None
                and url.hostname.endswith('.atlassian.net')
                and not url.username and not url.password and not port
                and not url.path.strip('/') and not url.query and not url.fragment
                and bool(self.admin_email and self.api_token)
                and bool(self.product_key and re.fullmatch(r'^[a-z][a-z0-9-]{1,49}$', self.product_key))
                and isinstance(mapping, dict) and mapping
                and all(isinstance(role, str) and role in roles
                        and isinstance(group, str) and _GROUP_ID.fullmatch(group)
                        for role, group in mapping.items())
                and access.application == 'jira' and access.requested_role in mapping
                and access.provider_resource == url.hostname)

    def provision(self, policy, access):
        if not self._configured(policy, access):
            return JiraResult('NOT_CONFIGURED')
        email = access.request.user.email.strip().lower()
        group_id = json.loads(self.role_map)[access.requested_role]
        try:
            with httpx.Client(base_url=self.site,
                              auth=httpx.BasicAuth(self.admin_email, self.api_token),
                              headers={'Accept': 'application/json'}, transport=self.transport,
                              timeout=10, follow_redirects=False) as client:
                search = client.get('/rest/api/3/user/search',
                                    params={'query': email, 'maxResults': 100})
                if search.status_code != 200:
                    return JiraResult('FAILED')
                candidates = search.json()
                if not isinstance(candidates, list):
                    return JiraResult('FAILED')
                exact = [item for item in candidates
                         if item.get('emailAddress', '').lower() == email
                         and item.get('accountType') == 'atlassian']
                if len(exact) != 1 or not exact[0].get('accountId'):
                    # Jira can hide email addresses. Never grant on a fuzzy name match.
                    return JiraResult('IDENTITY_MISMATCH' if candidates else 'USER_NOT_FOUND')
                account_id = exact[0]['accountId']
                if not exact[0].get('active'):
                    return JiraResult('IDENTITY_MISMATCH')
                path = '/rest/api/3/user/groups'
                current = client.get(path, params={'accountId': account_id})
                if current.status_code != 200 or not isinstance(current.json(), list):
                    return JiraResult('FAILED')
                if any(row.get('groupId') == group_id for row in current.json()):
                    return self._verify_product(client, account_id)
                added = client.post('/rest/api/3/group/user', params={'groupId': group_id},
                                    json={'accountId': account_id})
                if added.status_code != 201:
                    return JiraResult('FAILED')
                verified = client.get(path, params={'accountId': account_id})
                if verified.status_code != 200 or not isinstance(verified.json(), list):
                    return JiraResult('FAILED', managed=True)
                if not any(row.get('groupId') == group_id for row in verified.json()):
                    return JiraResult('FAILED', managed=True)
                result = self._verify_product(client, account_id)
                return JiraResult(result.status, result.verified, True)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return JiraResult('FAILED')

    def _verify_product(self, client, account_id):
        user = client.get('/rest/api/3/user',
                          params={'accountId': account_id, 'expand': 'applicationRoles'})
        if user.status_code != 200:
            return JiraResult('FAILED')
        body = user.json()
        if body.get('accountId') != account_id or not body.get('active'):
            return JiraResult('IDENTITY_MISMATCH')
        items = body.get('applicationRoles', {}).get('items', [])
        return (JiraResult('GRANTED', True)
                if any(item.get('key') == self.product_key for item in items)
                else JiraResult('PRODUCT_ACCESS_REQUIRED'))
