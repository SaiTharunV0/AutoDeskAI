"""Isolated tests; no local database, model, or credentials required."""
import os
import secrets
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from app import main
from app.database import Base, get_db
from sqlalchemy.orm import sessionmaker
from app.models import User, SoftwarePolicy, ApplicationPolicy, AuditLog, Device, SoftwareTask, now
from schema import AgentResponse, Intent
from auth import create_access_token
from agent import process_request, safe_message, UnsafeRequest
from endpoint_agent.agent import run_once
from endpoint_agent.installer import install

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        def database():
            with self.sessions() as db:
                yield db
        main.app.dependency_overrides[get_db] = database
        self.client = TestClient(main.app)
        self.password = secrets.token_urlsafe(20)
        self.employee = self.account("employee")
        self.other = self.account("other")
        self.admin = self.account("admin")
        with self.sessions() as db:
            db.get(User, self.admin["user"]["id"]).role = "admin"
            db.add(SoftwarePolicy(key="vscode"))
            db.add(ApplicationPolicy(key="tableau"))
            db.commit()
    def tearDown(self):
        self.client.close()
        main.app.dependency_overrides.clear()
        self.engine.dispose()
    def account(self, name):
        payload = {"name": name, "email": name + "@example.test", "password": self.password}
        self.assertEqual(self.client.post("/auth/register", json=payload).status_code, 201)
        return self.client.post(
            "/auth/login", json={"email": payload["email"], "password": self.password}).json()
    def headers(self, account=None):
        return {"Authorization": "Bearer " + (account or self.employee)["access_token"]}
    def request(self, intent, message, **kwargs):
        result = AgentResponse(intent=intent, software=kwargs.pop("software", None),
             application=kwargs.pop("application", None), message="untrusted model prose")
        with patch("app.workflows.process_request", return_value=result):
            return self.client.post("/requests", headers=self.headers(),
                json={"message": message, "idempotency_key": secrets.token_hex(16), **kwargs})
    def enroll(self, suffix="one"):
        response = self.client.post("/agent/register", headers=self.headers(self.admin),
            json={"device_id": "test-" + suffix, "hostname": "test", "os_info": "Test",
                  "owner_user_id": self.employee["user"]["id"]})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        data["headers"] = {"Authorization": "Bearer " + data["agent_token"]}
        self.client.get("/agent/heartbeat", headers=data["headers"])
        return data
    def test_authentication_and_rbac(self):
        self.assertEqual(self.client.get("/requests").status_code, 401)
        self.assertEqual(self.client.get("/admin/users", headers=self.headers()).status_code, 403)
        self.assertEqual(self.client.get("/admin/users", headers=self.headers(self.admin)).status_code, 200)
        self.assertEqual(self.client.get('/users',headers=self.headers()).status_code,403)
        self.assertEqual(self.client.put('/users/1',headers=self.headers(),json={
            'name':'changed','email':'changed@example.test'}).status_code,403)
        self.assertEqual(self.client.delete('/users/1',headers=self.headers()).status_code,403)
        response=self.client.put('/users/'+str(self.other['user']['id']),headers=self.headers(self.admin),json={
            'name':'Updated Name','email':'updated@example.test'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['name'],'Updated Name')
        self.assertEqual(self.client.post("/auth/login", json={"email":"employee@example.test","password":"bad"}).status_code, 401)
        token = create_access_token(self.employee["user"]["id"], -1)
        self.assertEqual(self.client.get("/auth/me", headers={"Authorization":"Bearer "+token}).status_code, 401)
        self.assertEqual(self.client.post("/auth/register", json={"email":"new@example.test","name":"x",
            "password":self.password, "role":"admin"}).status_code, 422)
    def test_password_and_request_ownership(self):
        row = self.request(Intent.PASSWORD_RESET, "I forgot my password").json()
        self.assertEqual(row["status"], "PENDING")
        self.assertEqual(self.client.get(f'/requests/{row["id"]}', headers=self.headers(self.other)).status_code, 404)
        response = self.client.post(f'/requests/{row["id"]}/password/confirm', headers=self.headers(),
                                   json={"confirm_simulation":True})
        self.assertEqual(response.json()["status"], "COMPLETED")
        self.assertIn("Simulated", response.json()["message"])
        history = self.client.get(f'/requests/{row["id"]}/history', headers=self.headers()).json()
        self.assertEqual([x["action"] for x in history], ["PASSWORD_RESET_REQUESTED","PASSWORD_RESET_COMPLETED"])
    def test_access_policy_and_unknown_application(self):
        self.assertEqual(self.request(Intent.ACCESS_REQUEST,"access Tableau",application="Tableau").json()["status"],"COMPLETED")
        self.assertEqual(self.request(Intent.ACCESS_REQUEST,"access unknown",application="unknown").json()["status"],"REJECTED")
        self.client.put("/admin/applications/tableau",headers=self.headers(self.admin),
                        json={"enabled":True,"required_role":"admin"})
        self.assertEqual(self.request(Intent.ACCESS_REQUEST,"access Tableau",application="Tableau").json()["status"],"REJECTED")
    def test_software_agent_end_to_end(self):
        device = self.enroll()
        row = self.request(Intent.SOFTWARE_INSTALL, "Install VS Code", software="vscode",
                           device_id=device["device"]["id"]).json()
        self.assertEqual(row["status"], "PENDING")
        client = self.client
        headers = device["headers"]
        class API:
            def heartbeat(self): return client.get("/agent/heartbeat",headers=headers).json()
            def tasks(self): return client.get("/agent/tasks",headers=headers).json()
            def report(self, task_id, result):
                response = client.post(f"/agent/tasks/{task_id}/result",headers=headers,json=result)
                assert response.status_code == 200, response.text
        run_once(API(), "test-one")
        final = self.client.get(f'/requests/{row["id"]}',headers=self.headers()).json()
        self.assertEqual(final["status"], "COMPLETED")
        self.assertIn("Simulated", final["message"])
        self.assertEqual(self.client.get("/agent/tasks",headers=headers).json(), [])
    def test_device_isolation_and_result_state(self):
        first, second = self.enroll(), self.enroll("two")
        row = self.request(Intent.SOFTWARE_INSTALL,"install vscode",software="vscode",device_id=first["device"]["id"]).json()
        task_id = row["task"]["id"]
        self.assertEqual(self.client.post(f"/agent/tasks/{task_id}/result",headers=first["headers"],
            json={"success":True}).status_code,409)
        self.assertEqual(self.client.post(f"/agent/tasks/{task_id}/result",headers=second["headers"],
            json={"success":True}).status_code,404)
        self.assertEqual(self.client.get("/agent/tasks",headers=self.headers()).status_code,401)
    def test_unapproved_software_and_invalid_device(self):
        self.assertEqual(self.request(Intent.SOFTWARE_INSTALL,"install malware",software="malware").json()["status"],"REJECTED")
        self.assertEqual(self.request(Intent.SOFTWARE_INSTALL,"install vscode",software="vscode",device_id=999).json()["status"],"REJECTED")
        with self.assertRaises(ValueError): install("powershell")
        with self.assertRaises(ValueError): install("vscode",False)
    def test_command_and_secrets_rejected(self):
        with patch("app.workflows.process_request") as ai:
            response = self.client.post("/requests",headers=self.headers(),json={
                "message":"execute powershell", "idempotency_key":"command-test"})
            self.assertEqual(response.status_code,400)
            ai.assert_not_called()
        with self.sessions() as db:
            self.assertIsNotNone(db.scalar(select(AuditLog).where(AuditLog.action=='REQUEST_REJECTED')))
        sentinel = secrets.token_hex(20)
        self.assertNotIn(sentinel, safe_message("hello "+sentinel))
        response = self.client.post("/auth/register", json={"name":"x","email":"bad","password":sentinel})
        self.assertNotIn(sentinel,response.text)
    def test_duplicate_request(self):
        result = AgentResponse(intent=Intent.PASSWORD_CHANGE,message="change")
        with patch("app.workflows.process_request",return_value=result) as ai:
            body={"message":"change password","idempotency_key":"same-request"}
            first=self.client.post("/requests",headers=self.headers(),json=body).json()
            second=self.client.post("/requests",headers=self.headers(),json=body).json()
            self.assertEqual(first["id"],second["id"])
            self.assertEqual(ai.call_count,1)
    def test_timeout(self):
        from datetime import timedelta
        device=self.enroll()
        row=self.request(Intent.SOFTWARE_INSTALL,"install vscode",software="vscode",device_id=device["device"]["id"]).json()
        with self.sessions() as db:
            db.get(SoftwareTask,row["task"]["id"]).created_at=now()-timedelta(hours=1)
            db.commit()
        final=self.client.get(f'/requests/{row["id"]}',headers=self.headers()).json()
        self.assertEqual(final["status"],"FAILED")

    def test_disabled_and_offline_device(self):
        from datetime import timedelta
        device = self.enroll()
        with self.sessions() as db:
            db.get(Device, device['device']['id']).last_seen = now()-timedelta(hours=1)
            db.commit()
        self.assertEqual(self.request(Intent.SOFTWARE_INSTALL,'install vscode',software='vscode',
            device_id=device['device']['id']).json()['status'],'FAILED')
        self.client.patch('/admin/devices/'+str(device['device']['id']),headers=self.headers(self.admin),
                          json={'status':'DISABLED'})
        self.assertEqual(self.client.get('/agent/heartbeat',headers=device['headers']).status_code,401)

    def test_policy_revoked_before_dispatch(self):
        device = self.enroll()
        row = self.request(Intent.SOFTWARE_INSTALL,'install vscode',software='vscode',device_id=device['device']['id']).json()
        self.client.put('/admin/software/vscode',headers=self.headers(self.admin),json={'enabled':False})
        self.assertEqual(self.client.get('/agent/tasks',headers=device['headers']).json(),[])
        self.assertEqual(self.client.get('/requests/'+str(row['id']),headers=self.headers()).json()['status'],'REJECTED')

    def test_ai_failure_is_audited(self):
        with patch('app.workflows.process_request',side_effect=RuntimeError('untrusted detail')):
            response=self.client.post('/requests',headers=self.headers(),json={
                'message':'install vscode','idempotency_key':'ai-failure'})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('untrusted detail',response.text)
        with self.sessions() as db:
            self.assertIsNotNone(db.scalar(select(AuditLog).where(AuditLog.action=='AI_REQUEST_FAILED')))

    def test_clarification_is_owned_and_target_cannot_be_fabricated(self):
        row=self.request(Intent.CLARIFICATION,'access').json()
        self.assertEqual(row['status'],'NEEDS_CLARIFICATION')
        with patch('app.workflows.process_request') as ai:
            response=self.client.post('/requests',headers=self.headers(self.other),json={
                'message':'Tableau','previous_request_id':row['id'],'idempotency_key':'stolen-context'})
            self.assertEqual(response.status_code,404)
            ai.assert_not_called()
        self.assertEqual(self.request(Intent.ACCESS_REQUEST,'access unknown',application='tableau').json()['status'],'REJECTED')

    def test_password_hash_and_no_credentials_in_audits(self):
        with self.sessions() as db:
            user=db.get(User,self.employee['user']['id'])
            self.assertNotEqual(user.password_hash,self.password)
            self.assertNotIn(self.password,str([(x.action,x.details) for x in db.scalars(select(AuditLog))]))
        response=self.client.post('/auth/register',json={
            'name':'duplicate','email':'employee@example.test','password':self.password})
        self.assertEqual(response.status_code,409)

class AITests(unittest.TestCase):
    def classify(self, message, result):
        with patch("agent.ollama.Client") as client:
            client.return_value.chat.return_value={"message":{"content":result.model_dump_json()}}
            response=process_request(message)
            return response,client
    def test_intents(self):
        for message,intent,field in [
            ("forgot password",Intent.PASSWORD_RESET,{}),
            ("change password",Intent.PASSWORD_CHANGE,{}),
            ("install VS Code",Intent.SOFTWARE_INSTALL,{"software":"vscode"}),
            ("access Tableau",Intent.ACCESS_REQUEST,{"application":"tableau"}),
            ("install",Intent.SOFTWARE_INSTALL,{})]:
            result,_=self.classify(message,AgentResponse(intent=intent,message="test",**field))
            self.assertEqual(result.intent,Intent.CLARIFICATION if message=="install" else intent)
    def test_ambiguous_request(self):
        result,_=self.classify("Tableau",AgentResponse(intent=Intent.ACCESS_REQUEST,application="tableau",message="test"))
        self.assertEqual(result.intent,Intent.CLARIFICATION)
    def test_no_raw_text_sent(self):
        marker=secrets.token_hex(20)
        _,client=self.classify("hello "+marker,AgentResponse(intent=Intent.CHAT,message="hi"))
        self.assertNotIn(marker,str(client.return_value.chat.call_args))
    def test_bad_response_and_offline(self):
        with patch("agent.ollama.Client") as client:
            client.return_value.chat.return_value={"message":{"content":"invalid JSON"}}
            with self.assertRaises(RuntimeError): process_request("hello")
            client.return_value.chat.side_effect=ConnectionError()
            with self.assertRaises(RuntimeError): process_request("hello")
    def test_followup(self):
        result=process_request("Tableau",AgentResponse(intent=Intent.CLARIFICATION,message="Which application?"))
        self.assertEqual(result.application,"tableau")
        self.assertEqual(result.intent,Intent.ACCESS_REQUEST)

    def test_ambiguous_actions_and_unknown_targets(self):
        with patch('agent.ollama.Client') as client:
            self.assertEqual(process_request('install vscode and access Tableau').intent,Intent.CLARIFICATION)
            client.assert_not_called()
        self.assertIn('unapproved_software',safe_message('install malware'))
        self.assertIn('unknown_application',safe_message('access unknown'))

    def test_missing_model_entity_uses_recognized_target(self):
        result,_=self.classify('access Tableau',AgentResponse(intent=Intent.ACCESS_REQUEST,message='identified'))
        self.assertEqual(result.application,'tableau')

if __name__ == "__main__":
    unittest.main()
