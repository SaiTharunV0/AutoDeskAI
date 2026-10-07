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
from endpoint_agent.installer import install, InstallationError
import config

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
            db.add(ApplicationPolicy(key="jira"))
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
             application=kwargs.pop("application", None), access_role=kwargs.pop("access_role", None),
             message="untrusted model prose")
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
        with patch.object(config, "ENTRA_TEST_ACCOUNT_UPN", "reserved@example.test"):
            reserved = {"name": "Reserved test", "email": "reserved@example.test",
                        "password": secrets.token_urlsafe(20)}
            self.assertEqual(self.client.post("/auth/register", json=reserved).status_code, 403)
            self.assertEqual(self.client.post("/users", headers=self.headers(self.admin),
                                              json=reserved).status_code, 201)
    def test_password_and_request_ownership(self):
        row = self.request(Intent.PASSWORD_RESET, "I forgot my password").json()
        self.assertEqual(row["status"], "PENDING")
        admin_rows = self.client.get("/admin/requests", headers=self.headers(self.admin)).json()
        self.assertEqual(next(item for item in admin_rows if item["id"] == row["id"])["original_message"],
                         "i forgot my password")
        self.assertEqual(self.client.get(f'/requests/{row["id"]}', headers=self.headers(self.other)).status_code, 404)
        with patch.object(config, "ENTRA_TEST_ACCOUNT_UPN", "employee@example.test"), \
                patch("app.main.get_password_service") as provider:
            provider.return_value.reset_url.return_value = "https://passwordreset.microsoftonline.com/"
            provider.return_value.verify_reset.side_effect = [False, True]
            start = self.client.post(f'/requests/{row["id"]}/password/reset/start', headers=self.headers())
            self.assertEqual(start.status_code, 200)
            self.assertEqual(start.json()["redirect_url"], "https://passwordreset.microsoftonline.com/")
            pending = self.client.post(f'/requests/{row["id"]}/password/reset/verify', headers=self.headers())
            self.assertFalse(pending.json()["verified"])
            response = self.client.post(f'/requests/{row["id"]}/password/reset/verify', headers=self.headers())
            self.assertTrue(response.json()["verified"])
            self.assertEqual(response.json()["request"]["status"], "COMPLETED")
        history = self.client.get(f'/requests/{row["id"]}/history', headers=self.headers()).json()
        self.assertEqual([x["action"] for x in history], [
            "PASSWORD_RESET_REQUESTED", "PASSWORD_RESET_STARTED",
            "PASSWORD_RESET_VERIFICATION_PENDING", "PASSWORD_RESET_COMPLETED"])

    def test_password_change_sends_secrets_only_to_provider(self):
        row = self.request(Intent.PASSWORD_CHANGE, "change my password").json()
        current, new = secrets.token_urlsafe(20), secrets.token_urlsafe(20)
        with patch.object(config, "ENTRA_TEST_ACCOUNT_UPN", "employee@example.test"), \
                patch("services.password.EntraPasswordService.change_password") as change:
            response = self.client.post(
                f'/requests/{row["id"]}/password/change',
                headers={**self.headers(), "X-Entra-Access-Token": "delegated-token"},
                json={"current_password": current, "new_password": new})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "COMPLETED")
        change.assert_called_once_with("delegated-token", current, new)
        with self.sessions() as db:
            self.assertNotIn(current, str([(x.action, x.details) for x in db.scalars(select(AuditLog))]))
            self.assertNotIn(new, str([(x.action, x.details) for x in db.scalars(select(AuditLog))]))

    def test_request_cancellation_is_owner_scoped_and_stops_unstarted_work(self):
        device = self.enroll()
        software = self.request(
            Intent.SOFTWARE_INSTALL, "Install VS Code", software="vscode",
            device_id=device["device"]["id"]).json()
        self.assertEqual(self.client.post(
            f'/requests/{software["id"]}/cancel', headers=self.headers(self.other)).status_code, 404)
        cancelled = self.client.post(
            f'/requests/{software["id"]}/cancel', headers=self.headers())
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")
        self.assertEqual(cancelled.json()["task"]["status"], "CANCELLED")
        self.assertEqual(self.client.get("/agent/tasks", headers=device["headers"]).json(), [])

        with patch.object(config, "JIRA_TEST_ACCOUNT_EMAIL", "employee@example.test"):
            approval = self.request(
                Intent.ACCESS_REQUEST, "give me project admin access to Jira",
                application="jira", access_role="project_admin").json()
        cancelled_approval = self.client.post(
            f'/requests/{approval["id"]}/cancel', headers=self.headers())
        self.assertEqual(cancelled_approval.status_code, 200, cancelled_approval.text)
        self.assertEqual(cancelled_approval.json()["status"], "CANCELLED")

        reset = self.request(Intent.PASSWORD_RESET, "reset my password").json()
        with patch.object(config, "ENTRA_TEST_ACCOUNT_UPN", "employee@example.test"), \
                patch("app.main.get_password_service") as provider:
            provider.return_value.reset_url.return_value = "https://passwordreset.microsoftonline.com/"
            self.assertEqual(self.client.post(
                f'/requests/{reset["id"]}/password/reset/start',
                headers=self.headers()).status_code, 200)
        self.assertEqual(self.client.post(
            f'/requests/{reset["id"]}/cancel', headers=self.headers()).status_code, 409)

    def test_access_policy_and_unknown_application(self):
        with patch.object(config, "JIRA_TEST_ACCOUNT_EMAIL", "employee@example.test"), \
                patch("services.jira.JiraAccessService.provision", return_value=True) as provision:
            granted = self.request(Intent.ACCESS_REQUEST, "give me developer access to Jira",
                                   application="jira", access_role="developer").json()
            self.assertEqual(granted["status"], "COMPLETED")
            self.assertEqual(granted["access"]["requested_role"], "developer")
            provision.assert_called_once_with("developer")
            pending = self.request(Intent.ACCESS_REQUEST, "give me project admin access to Jira",
                                   application="jira", access_role="project_admin").json()
            self.assertEqual(pending["status"], "AWAITING_APPROVAL")
            approved = self.client.post(
                f'/admin/requests/{pending["id"]}/approval', headers=self.headers(self.admin),
                json={"approved": True})
            self.assertEqual(approved.json()["status"], "COMPLETED")
            self.assertEqual(approved.json()["access"]["requested_role"], "project_admin")
        rejected = self.request(Intent.ACCESS_REQUEST, "access unknown", application="unknown",
                                access_role="developer").json()
        self.assertEqual(rejected["status"], "REJECTED")
        self.client.put("/admin/applications/jira", headers=self.headers(self.admin),
                        json={"enabled": True, "required_role": "admin"})
        denied = self.request(Intent.ACCESS_REQUEST, "give me developer access to Jira",
                              application="jira", access_role="developer").json()
        self.assertEqual(denied["status"], "REJECTED")
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
        run_once(API(), "test-one", simulation=True)
        final = self.client.get(f'/requests/{row["id"]}',headers=self.headers()).json()
        self.assertEqual(final["status"], "COMPLETED")
        self.assertIn("Simulated", final["message"])
        actions = [item["action"] for item in self.client.get(
            f'/requests/{row["id"]}/history', headers=self.headers()).json()]
        self.assertEqual(actions, [
            "SOFTWARE_INSTALL_REQUESTED", "SOFTWARE_INSTALL_STARTED",
            "SOFTWARE_INSTALL_VERIFYING", "SOFTWARE_INSTALL_COMPLETED"])
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
        self.assertEqual(install("chrome", True), {"success": True, "simulated": True})
        with patch("endpoint_agent.installer.os.name", "posix"):
            with self.assertRaises(InstallationError):
                install("vscode", False)
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
        self.assertEqual(self.request(Intent.ACCESS_REQUEST,'access unknown',application='jira',
            access_role='developer').json()['status'],'REJECTED')

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
            ("give me developer access to Jira",Intent.ACCESS_REQUEST,
             {"application":"jira","access_role":"developer"}),
            ("install",Intent.SOFTWARE_INSTALL,{})]:
            result,_=self.classify(message,AgentResponse(intent=intent,message="test",**field))
            self.assertEqual(result.intent,Intent.CLARIFICATION if message=="install" else intent)
    def test_ambiguous_request(self):
        result,_=self.classify("Jira",AgentResponse(intent=Intent.ACCESS_REQUEST,application="jira",message="test"))
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
        result=process_request("Jira Developer",AgentResponse(
            intent=Intent.CLARIFICATION,message="Which application do you need access to?"))
        self.assertEqual(result.application,"jira")
        self.assertEqual(result.access_role,"developer")
        self.assertEqual(result.intent,Intent.ACCESS_REQUEST)

    def test_ambiguous_actions_and_unknown_targets(self):
        with patch('agent.ollama.Client') as client:
            self.assertEqual(process_request('install vscode and access Jira').intent,Intent.CLARIFICATION)
            client.assert_not_called()
        self.assertIn('unapproved_software',safe_message('install malware'))
        self.assertIn('unknown_application',safe_message('access unknown'))

    def test_missing_model_entity_uses_recognized_target(self):
        result,_=self.classify('give me developer access to Jira',
            AgentResponse(intent=Intent.ACCESS_REQUEST,message='identified'))
        self.assertEqual(result.application,'jira')
        self.assertEqual(result.access_role,'developer')

class IntegrationTests(unittest.TestCase):
    class Response:
        def __init__(self, data, status_code=200):
            self.data = data
            self.status_code = status_code
        def json(self):
            return self.data
        def raise_for_status(self):
            return None

    def test_entra_sspr_verification_uses_only_configured_test_account(self):
        from datetime import datetime, timezone
        from services.password import EntraPasswordService
        service = EntraPasswordService()
        with patch.object(config, "ENTRA_TEST_ACCOUNT_UPN", "test@example.test"), \
                patch.object(service, "_graph_token", return_value="app-token"), \
                patch("services.password.httpx.get", return_value=self.Response({
                    "userPrincipalName": "test@example.test",
                    "lastPasswordChangeDateTime": "2026-10-07T01:00:00Z"})) as graph_get:
            self.assertTrue(service.verify_reset(datetime(2026, 10, 7, 0, 59, tzinfo=timezone.utc)))
            self.assertFalse(service.verify_reset(datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc)))
        self.assertEqual(graph_get.call_args.kwargs["headers"]["Authorization"], "Bearer app-token")

    def test_entra_password_change_checks_identity_then_calls_change_api(self):
        from services.password import EntraPasswordService, GRAPH_URL
        current, new = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        with patch.object(config, "ENTRA_TEST_ACCOUNT_UPN", "test@example.test"), \
                patch("services.password.httpx.get", return_value=self.Response({
                    "userPrincipalName": "test@example.test"})), \
                patch("services.password.httpx.post", return_value=self.Response({}, 204)) as graph_post:
            EntraPasswordService().change_password("delegated", current, new)
        self.assertEqual(graph_post.call_args.args[0], f"{GRAPH_URL}/me/changePassword")
        self.assertEqual(graph_post.call_args.kwargs["json"],
                         {"currentPassword": current, "newPassword": new})
        with patch.object(config, "ENTRA_TEST_ACCOUNT_UPN", "test@example.test"), \
                patch("services.password.httpx.get", return_value=self.Response({
                    "userPrincipalName": "other@example.test"})), \
                patch("services.password.httpx.post") as graph_post:
            with self.assertRaises(PermissionError):
                EntraPasswordService().change_password("delegated", current, new)
            graph_post.assert_not_called()

    def test_jira_provision_maps_role_and_verifies_test_account(self):
        from services.jira import JiraAccessService

        class JiraClient:
            def __init__(self):
                self.added = False
                self.add_calls = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def get(self, path, params=None):
                if path.endswith("/user"):
                    return IntegrationTests.Response({
                        "accountId": "jira-test-id", "emailAddress": "test@example.test"})
                if path.endswith("/project/TEST/role"):
                    return IntegrationTests.Response({"Developers": "https://jira.test/role/42"})
                actors = ([{"actorUser": {"accountId": "jira-test-id"}}] if self.added else [])
                return IntegrationTests.Response({"actors": actors})
            def post(self, path, json):
                self.add_calls.append((path, json))
                self.added = True
                return IntegrationTests.Response({}, 201)

        client = JiraClient()
        with patch.object(config, "JIRA_BASE_URL", "https://jira.example.test"), \
                patch.object(config, "JIRA_EMAIL", "service@example.test"), \
                patch.object(config, "JIRA_API_TOKEN", "jira-api-token"), \
                patch.object(config, "JIRA_PROJECT_KEY", "TEST"), \
                patch.object(config, "JIRA_TEST_ACCOUNT_EMAIL", "test@example.test"), \
                patch.object(config, "JIRA_TEST_ACCOUNT_ID", "jira-test-id"), \
                patch("services.jira.httpx.Client", return_value=client):
            self.assertTrue(JiraAccessService().provision("developer"))
        self.assertEqual(client.add_calls, [
            ("/rest/api/3/project/TEST/role/42", {"user": ["jira-test-id"]})])

    def test_jira_rejects_account_email_mismatch_before_role_assignment(self):
        from services.jira import JiraAccessService, JiraIntegrationError

        class JiraClient:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def get(self, path, params=None):
                return IntegrationTests.Response({
                    "accountId": "different-id", "emailAddress": "other@example.test"})
            def post(self, path, json):
                raise AssertionError("Mismatched account must never receive a role")

        with patch.object(config, "JIRA_BASE_URL", "https://jira.example.test"), \
                patch.object(config, "JIRA_EMAIL", "service@example.test"), \
                patch.object(config, "JIRA_API_TOKEN", "jira-api-token"), \
                patch.object(config, "JIRA_PROJECT_KEY", "TEST"), \
                patch.object(config, "JIRA_TEST_ACCOUNT_EMAIL", "test@example.test"), \
                patch.object(config, "JIRA_TEST_ACCOUNT_ID", "jira-test-id"), \
                patch("services.jira.httpx.Client", return_value=JiraClient()):
            with self.assertRaises(JiraIntegrationError):
                JiraAccessService().provision("developer")

    @unittest.skipUnless(os.name == "nt", "Real installer dispatch is Windows-only")
    def test_installer_runs_only_fixed_winget_packages_and_verifies_files(self):
        from pathlib import Path
        from types import SimpleNamespace
        from endpoint_agent import installer

        for software, package, scope in (
            ("vscode", "Microsoft.VisualStudioCode", "user"),
            ("chrome", "Google.Chrome", "machine"),
        ):
            with self.subTest(software=software), \
                    patch.object(installer, "_installed_paths", return_value=(Path("verified.exe"),)), \
                    patch.object(installer, "_winget_executable", return_value=Path("C:/Windows/winget.exe")), \
                    patch.object(Path, "is_file", side_effect=[False, True]), \
                    patch("endpoint_agent.installer.subprocess.run",
                          return_value=SimpleNamespace(returncode=0)) as run:
                self.assertEqual(installer.install(software, simulation=False),
                                 {"success": True, "simulated": False})
                command = run.call_args.args[0]
                self.assertIn(package, command)
                self.assertEqual(command[command.index("--scope") + 1], scope)
                self.assertIs(run.call_args.kwargs["shell"], False)

if __name__ == "__main__":
    unittest.main()
