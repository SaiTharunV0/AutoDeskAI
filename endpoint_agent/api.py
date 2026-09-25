import httpx
class AgentAPI:
    def __init__(self, server_url, token):
        self.client = httpx.Client(base_url=server_url, headers={"Authorization": "Bearer " + token}, timeout=30)
    def heartbeat(self):
        response = self.client.get("/agent/heartbeat")
        response.raise_for_status()
        return response.json()
    def tasks(self):
        response = self.client.get("/agent/tasks")
        response.raise_for_status()
        return response.json()
    def report(self, task_id, result):
        response = self.client.post(f"/agent/tasks/{task_id}/result", json=result)
        response.raise_for_status()
    def close(self):
        self.client.close()
