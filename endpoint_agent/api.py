import httpx
from time import monotonic
class AgentAPI:
    def __init__(self, server_url, token, *, transport=None, now=monotonic):
        self.client = httpx.Client(base_url=server_url, headers={"Authorization": "Bearer " + token}, timeout=30, transport=transport)
        self._now = now
        self._device = None
        self._heartbeat_at = 0
    def heartbeat(self):
        # /agent/tasks also updates last_seen. Revalidate identity periodically
        # instead of issuing two heartbeat writes for every task poll.
        if self._device is not None and self._now() - self._heartbeat_at < 30:
            return self._device
        response = self.client.get("/agent/heartbeat")
        response.raise_for_status()
        self._device = response.json()
        self._heartbeat_at = self._now()
        return self._device
    def tasks(self):
        response = self.client.get("/agent/tasks")
        response.raise_for_status()
        return response.json()
    def report(self, task_id, result):
        response = self.client.post(f"/agent/tasks/{task_id}/result", json=result)
        response.raise_for_status()
    def close(self):
        self.client.close()
