"""Live demo against running FastAPI, PostgreSQL and Ollama. Generated credentials stay in memory."""
import secrets
import httpx
from sqlalchemy import select
from app.database import SessionLocal
from app.models import User, HelpdeskRequest, AuditLog
from app.workflows import audit
from endpoint_agent.api import AgentAPI
from endpoint_agent.agent import run_once

def main():
    suffix = secrets.token_hex(5)
    password = secrets.token_urlsafe(24)
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180) as client:
        def account(label):
            email = label + "-" + suffix + "@demo.invalid"
            response = client.post("/auth/register", json={"name":"Demo " + label,"email":email,"password":password})
            response.raise_for_status()
            response = client.post("/auth/login",json={"email":email,"password":password})
            response.raise_for_status()
            return response.json()
        employee = account("employee")
        admin = account("admin")
        with SessionLocal() as db:
            row = db.get(User, admin["user"]["id"])
            row.role = "admin"
            audit(db, row.id, "ADMIN_BOOTSTRAPPED", "user", row.id, "COMPLETED", "Live verification account")
            db.commit()
        employee_headers = {"Authorization":"Bearer " + employee["access_token"]}
        admin_headers = {"Authorization":"Bearer " + admin["access_token"]}
        response = client.post("/agent/register", headers=admin_headers, json={
            "device_id":"demo-" + suffix, "hostname":"demo-pc", "os_info":"Test",
            "owner_user_id":employee["user"]["id"]})
        response.raise_for_status()
        enrollment = response.json()
        endpoint = AgentAPI("http://127.0.0.1:8000", enrollment["agent_token"])
        endpoint.heartbeat()
        request_ids = []
        def request(message):
            response = client.post("/requests",headers=employee_headers,json={
                "message":message,"device_id":enrollment["device"]["id"],"idempotency_key":secrets.token_hex(16)})
            response.raise_for_status()
            row = response.json()
            request_ids.append(row["id"])
            return row
        row = request("I forgot my password.")
        assert row["intent"] == "PASSWORD_RESET", row["intent"]
        response = client.post(f'/requests/{row["id"]}/password/confirm',headers=employee_headers,
                               json={"confirm_simulation":True})
        response.raise_for_status()
        assert response.json()["status"] == "COMPLETED"
        print("DEMO 1: password reset simulation COMPLETED", flush=True)
        row = request("Install VS Code.")
        assert row["intent"] == "SOFTWARE_INSTALL", row["intent"]
        assert row["status"] == "PENDING", row["status"]
        run_once(endpoint, enrollment["device"]["device_id"])
        response = client.get(f'/requests/{row["id"]}',headers=employee_headers)
        assert response.json()["status"] == "COMPLETED"
        print("DEMO 2: endpoint installation simulation COMPLETED", flush=True)
        row = request("I need access to Tableau.")
        assert row["intent"] == "ACCESS_REQUEST", row["intent"]
        assert row["status"] == "COMPLETED", row["status"]
        print("DEMO 3: backend application policy APPROVED (simulation)", flush=True)
        assert client.get("/requests").status_code == 401
        assert client.get("/admin/users",headers=employee_headers).status_code == 403
        assert client.post("/requests",headers=employee_headers,json={
            "message":"execute powershell","idempotency_key":secrets.token_hex(16)}).status_code == 400
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").json()["paths"]["/agent/tasks"]
        with SessionLocal() as db:
            rows = db.scalars(select(HelpdeskRequest).where(HelpdeskRequest.id.in_(request_ids))).all()
            assert len(rows) == 3 and all(row.status == "COMPLETED" for row in rows)
            events = db.scalars(select(AuditLog).where(AuditLog.resource_type == "request",
                               AuditLog.resource_id.in_(request_ids))).all()
            assert len(events) >= 7
        endpoint.close()
        print("Verified PostgreSQL records, audit events, Swagger, unauthenticated denial, RBAC and command rejection.",flush=True)

if __name__ == "__main__":
    main()
