"""Isolated tests; no local database, model, or credentials required."""
import os
import secrets
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(48)
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text, event
from sqlalchemy.pool import StaticPool
from app import main
from app.database import Base, get_db, upgrade_user_profile, upgrade_query_indexes
from sqlalchemy.orm import sessionmaker
from app.models import User, SoftwarePolicy, ApplicationPolicy, AuditLog, Device, SoftwareTask, HelpdeskRequest, now
from app.workflows import correct_legacy_password_requests, expire_tasks
from schema import AgentResponse, Intent
from auth import create_access_token
from agent import process_request, safe_message, UnsafeRequest, get_model_client, close_model_client
from endpoint_agent.agent import run_once
from endpoint_agent.installer import install

def registration_payload(name, email, password):
    return {"first_name": name, "last_name": "User", "date_of_birth": "1995-06-15",
            "username": name, "email": email, "password": password,
            "confirm_password": password}

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
        payload = registration_payload(name, name + "@example.test", self.password)
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
        self.assertEqual(self.client.post("/auth/register", json=registration_payload('six', 'six@example.test', 'abcdef')).status_code, 201)
        self.assertEqual(self.client.post("/auth/register", json=registration_payload('five', 'five@example.test', 'abcde')).status_code, 422)
        self.assertEqual(self.client.get('/users',headers=self.headers()).status_code,403)
        self.assertEqual(self.client.put('/users/1',headers=self.headers(),json={
            'name':'changed','email':'changed@example.test'}).status_code,403)
        self.assertEqual(self.client.delete('/users/1',headers=self.headers()).status_code,403)
        response=self.client.put('/users/'+str(self.other['user']['id']),headers=self.headers(self.admin),json={
            'name':'Updated Name','email':'updated@example.test'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['name'],'Updated Name')
        self.assertEqual(self.client.post("/auth/login", json={"email":"employee@example.test","password":"bad"}).status_code, 401)
        wrong = self.client.post('/auth/login', json={'identifier':'employee','password':'bad'})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json()['detail'], 'Username/email or password is wrong')
        self.assertEqual(self.client.post('/auth/login', json={
            'identifier':'employee', 'password':self.password}).status_code, 200)
        self.assertEqual(self.client.post('/auth/login', json={
            'identifier':'employee@example.test', 'password':self.password}).status_code, 200)
        self.assertEqual(self.client.post('/auth/register', json=registration_payload(
            'employee', 'another@example.test', self.password)).json()['detail'], 'Username already taken')
        mismatch = registration_payload('mismatch', 'mismatch@example.test', self.password)
        mismatch['confirm_password'] = 'different'
        self.assertEqual(self.client.post('/auth/register', json=mismatch).status_code, 422)
        token = create_access_token(self.employee["user"]["id"], -1)
        self.assertEqual(self.client.get("/auth/me", headers={"Authorization":"Bearer "+token}).status_code, 401)
        self.assertEqual(self.client.post("/auth/register", json={**registration_payload('new', 'new@example.test', self.password), "role":"admin"}).status_code, 422)
    def test_password_and_request_ownership(self):
        row = self.request(Intent.PASSWORD_RESET, "I forgot my password").json()
        self.assertEqual(row["status"], "AWAITING_USER_ACTION")
        admin_rows = self.client.get("/admin/requests", headers=self.headers(self.admin)).json()
        self.assertEqual(next(item for item in admin_rows if item["id"] == row["id"])["original_message"],
                         "i forgot my password")
        self.assertEqual(self.client.get(f'/requests/{row["id"]}', headers=self.headers(self.other)).status_code, 404)
        self.assertEqual(self.client.get(f'/requests/{row["id"]}', headers=self.headers(self.admin)).status_code, 404)
        self.assertEqual(self.client.post(f'/requests/{row["id"]}/password/action').status_code, 401)
        self.assertEqual(self.client.post(f'/requests/{row["id"]}/password/action',
            headers={"Authorization":"Bearer invalid"}).status_code, 401)
        self.assertEqual(self.client.post(f'/requests/{row["id"]}/password/action',
            headers=self.headers(self.other)).status_code, 404)
        response = self.client.post(f'/requests/{row["id"]}/password/action', headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["url"], "https://passwordreset.microsoftonline.com/")
        self.assertEqual(response.json()["status"], "AWAITING_USER_ACTION")
        self.assertEqual(self.client.get(f'/requests/{row["id"]}',headers=self.headers()).json()["status"],
                         "AWAITING_USER_ACTION")
        self.assertEqual(self.client.post(f'/requests/{row["id"]}/password/confirm',
            headers=self.headers(), json={"confirm_simulation": True}).status_code, 404)
        history = self.client.get(f'/requests/{row["id"]}/history', headers=self.headers()).json()
        self.assertEqual([x["action"] for x in history], ["PASSWORD_RESET_REQUESTED","PASSWORD_RESET_LINK_OPENED"])
        self.assertNotIn(self.password, str(history))
        self.assertNotIn(self.employee["access_token"], str(history))

    def test_password_reset_uses_validated_configuration_without_completion(self):
        row = self.request(Intent.PASSWORD_RESET, "forgot password").json()
        with patch.object(main.config, "MICROSOFT_SSPR_URL", "https://tenant.example/reset"):
            response = self.client.post(f'/requests/{row["id"]}/password/action', headers=self.headers())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["url"], "https://tenant.example/reset")
        with patch.object(main.config, "MICROSOFT_SSPR_URL", "http://unsafe.example/reset"):
            response = self.client.post(f'/requests/{row["id"]}/password/action', headers=self.headers())
            self.assertEqual(response.status_code, 503)
        self.assertEqual(self.client.get(f'/requests/{row["id"]}', headers=self.headers()).json()["status"],
                         "AWAITING_USER_ACTION")
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_password_change_and_rate_limit(self):
        row = self.request(Intent.PASSWORD_CHANGE, "change my password").json()
        action = self.client.post(f'/requests/{row["id"]}/password/action', headers=self.headers()).json()
        self.assertEqual(action["url"], "https://myaccount.microsoft.com/")
        self.assertEqual(action["status"], "AWAITING_USER_ACTION")
        for _ in range(4):
            self.assertEqual(self.request(Intent.PASSWORD_RESET, "forgot password").status_code, 201)
        self.assertEqual(self.request(Intent.PASSWORD_RESET, "forgot password").status_code, 429)
        self.assertEqual(self.client.get('/requests',headers=self.headers()).status_code, 200)

    def test_legacy_simulation_status_is_corrected(self):
        row = self.request(Intent.PASSWORD_CHANGE, "change password").json()
        with self.sessions() as db:
            legacy = db.get(HelpdeskRequest, row["id"])
            legacy.status = "COMPLETED"
            legacy.message = "Simulated password operation completed. Your actual login password is unchanged."
            db.commit()
            correct_legacy_password_requests(db)
        updated = self.client.get(f'/requests/{row["id"]}', headers=self.headers()).json()
        self.assertEqual(updated["status"], "AWAITING_USER_ACTION")
        self.assertIn("Legacy simulation", updated["message"])
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
        response = self.client.post("/auth/register", json=registration_payload('invalid', 'bad', sentinel))
        self.assertNotIn(sentinel,response.text)
    def test_duplicate_request(self):
        result = AgentResponse(intent=Intent.PASSWORD_CHANGE,message="change")
        with patch("app.workflows.process_request",return_value=result) as ai:
            body={"message":"change password","idempotency_key":"same-request"}
            first=self.client.post("/requests",headers=self.headers(),json=body).json()
            second=self.client.post("/requests",headers=self.headers(),json=body).json()
            self.assertEqual(first["id"],second["id"])
            self.assertEqual(ai.call_count,1)

    def test_general_chat_does_not_create_request(self):
        before = len(self.client.get('/requests', headers=self.headers()).json())
        with patch('app.workflows.process_request', side_effect=lambda message, previous:
                   AgentResponse(intent=Intent.CHAT, message=f'AI reply to {message}')):
            for message in ('hello', 'how are you', 'Tableau'):
                response = self.client.post('/requests', headers=self.headers(), json={
                    'message': message, 'idempotency_key': secrets.token_hex(16)})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['intent'], 'CHAT')
                self.assertEqual(response.json()['message'], f'AI reply to {message}')
                self.assertIsNone(response.json()['id'])
        self.assertEqual(len(self.client.get('/requests', headers=self.headers()).json()), before)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(HelpdeskRequest).where(HelpdeskRequest.user_id == self.employee['user']['id'])), None)
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
        response=self.client.post('/auth/register',json=registration_payload('duplicate', 'employee@example.test', self.password))
        self.assertEqual(response.status_code,409)

    def test_existing_user_table_gets_profile_columns(self):
        legacy_engine = create_engine('sqlite://', poolclass=StaticPool)
        try:
            with legacy_engine.begin() as connection:
                connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(100), email VARCHAR(150), password_hash VARCHAR(255), role VARCHAR(50))'))
                connection.execute(text("INSERT INTO users VALUES (1, 'Existing User', 'existing@example.test', 'hash', 'employee')"))
            upgrade_user_profile(legacy_engine)
            upgrade_user_profile(legacy_engine)
            columns = {column['name'] for column in inspect(legacy_engine).get_columns('users')}
            self.assertTrue({'first_name', 'last_name', 'date_of_birth', 'username'} <= columns)
            with legacy_engine.connect() as connection:
                self.assertEqual(connection.scalar(text('SELECT name FROM users WHERE id=1')), 'Existing User')
        finally:
            legacy_engine.dispose()

    def test_request_lists_use_constant_query_count(self):
        device = self.enroll()
        with self.sessions() as db:
            for i in range(60):
                row = HelpdeskRequest(user_id=self.employee['user']['id'], intent='SOFTWARE_INSTALL',
                    status='COMPLETED', message='Done', idempotency_key=f'query-check-{i}')
                db.add(row)
                db.flush()
                db.add(SoftwareTask(request_id=row.id, device_id=device['device']['id'],
                    software='vscode', status='COMPLETED'))
            db.commit()
        queries = []
        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith('SELECT'):
                queries.append(statement)
        event.listen(self.engine, 'before_cursor_execute', record)
        try:
            for path, account in [('/requests', self.employee), ('/admin/requests', self.admin)]:
                queries.clear()
                response = self.client.get(path, headers=self.headers(account))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()), 60)
                self.assertEqual(response.headers.get('content-encoding'), 'gzip')
                self.assertLess(int(response.headers['content-length']), len(response.content))
                self.assertTrue(all(row['task']['software'] == 'vscode' for row in response.json()))
                self.assertLessEqual(len(queries), 4, f'{path}: {len(queries)} SELECTs for 60 rows')
        finally:
            event.remove(self.engine, 'before_cursor_execute', record)

    def test_query_indexes_upgrade_existing_tables_idempotently(self):
        names = {'ix_devices_owner', 'ix_devices_token', 'ix_requests_user_id',
                 'ix_tasks_status_created', 'ix_tasks_device_status', 'ix_audit_resource'}
        for table in Base.metadata.sorted_tables:
            for index in table.indexes:
                if index.name in names:
                    index.drop(self.engine)
        upgrade_query_indexes(self.engine)
        upgrade_query_indexes(self.engine)
        inspector = inspect(self.engine)
        present = {index['name'] for table in Base.metadata.sorted_tables
                   for index in inspector.get_indexes(table.name)}
        self.assertTrue(names <= present)
        with self.sessions() as db:
            self.assertIsNotNone(db.get(User, self.employee['user']['id']))

    def test_idle_expiration_does_not_commit(self):
        with self.sessions() as db, patch.object(db, 'commit', wraps=db.commit) as commit:
            expire_tasks(db)
            commit.assert_not_called()

    def test_model_call_releases_database_connection(self):
        active = [0]
        def checkout(*args): active[0] += 1
        def checkin(*args): active[0] -= 1
        def classify(*args):
            self.assertEqual(active[0], 0, 'Model call held a database connection')
            return AgentResponse(intent=Intent.CHAT, message='Hello')
        event.listen(self.engine, 'checkout', checkout)
        event.listen(self.engine, 'checkin', checkin)
        try:
            with patch('app.workflows.process_request', side_effect=classify):
                response = self.client.post('/requests', headers=self.headers(), json={
                    'message': 'hello', 'idempotency_key': 'connection-release-test'})
            self.assertEqual(response.status_code, 200)
        finally:
            event.remove(self.engine, 'checkout', checkout)
            event.remove(self.engine, 'checkin', checkin)

    def test_admin_invite_gate_and_role_portals(self):
        payload = {**registration_payload('invited', 'invited@example.test', self.password), 'account_role': 'admin'}
        code = secrets.token_urlsafe(32)
        with patch.object(main.config, 'ADMIN_REGISTRATION_CODE', ''):
            self.assertEqual(self.client.post('/auth/register', json=payload).status_code, 503)
        with patch.object(main.config, 'ADMIN_REGISTRATION_CODE', code):
            self.assertEqual(self.client.post('/auth/register', json=payload).status_code, 403)
            self.assertEqual(self.client.post('/auth/register', json={**payload, 'admin_invite_code': 'wrong'}).status_code, 403)
            response = self.client.post('/auth/register', json={**payload, 'admin_invite_code': code})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['user']['role'], 'admin')
        self.assertNotIn(code, response.text)
        self.assertEqual(self.client.get('/admin/users', headers=self.headers(response.json())).status_code, 200)
        for identifier, role in [('invited', 'employee'), ('employee', 'admin')]:
            self.assertEqual(self.client.post('/auth/login', json={
                'identifier': identifier, 'password': self.password, 'expected_role': role}).status_code, 403)

class EndpointEfficiencyTests(unittest.TestCase):
    def test_heartbeat_identity_cache_expires(self):
        import httpx
        from endpoint_agent.api import AgentAPI
        clock, paths = [0], []
        def handle(request):
            paths.append(request.url.path)
            return httpx.Response(200, json={'id': 1, 'device_id': 'endpoint-test'})
        api = AgentAPI('https://example.test', 'test-token', transport=httpx.MockTransport(handle), now=lambda: clock[0])
        try:
            api.heartbeat()
            clock[0] = 10
            api.heartbeat()
            self.assertEqual(len(paths), 1)
            clock[0] = 31
            api.heartbeat()
            self.assertEqual(len(paths), 2)
        finally:
            api.close()

    def test_terminal_result_conflict_does_not_block_new_tasks(self):
        import httpx
        from unittest.mock import Mock
        for status in (404, 409, 503):
            api = Mock()
            api.heartbeat.return_value = {'id': 1, 'device_id': 'endpoint-test'}
            api.tasks.return_value = []
            response = httpx.Response(status, request=httpx.Request('POST', 'https://example.test/result'))
            api.report.side_effect = httpx.HTTPStatusError('report rejected', request=response.request, response=response)
            pending = {1: {'success': True, 'simulated': True}}
            if status == 503:
                with self.assertRaises(httpx.HTTPStatusError):
                    run_once(api, 'endpoint-test', pending=pending)
                self.assertIn(1, pending)
                api.tasks.assert_not_called()
            else:
                run_once(api, 'endpoint-test', pending=pending)
                self.assertEqual(pending, {})
                api.tasks.assert_called_once()

class AITests(unittest.TestCase):
    def setUp(self):
        close_model_client()
    def tearDown(self):
        close_model_client()
    def classify(self, message, result):
        close_model_client()
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
        with patch('agent.get_model_client') as client:
            client.return_value.chat.return_value={'message': {'content': 'Tableau is a data visualization tool.'}}
            result=process_request('Tableau')
        self.assertEqual(result.intent,Intent.CHAT)
        self.assertEqual(result.message, 'Tableau is a data visualization tool.')
        self.assertEqual(client.return_value.chat.call_args.kwargs['messages'][-1]['content'], 'Tableau')
    def test_general_chat_uses_original_text(self):
        with patch('agent.get_model_client') as client:
            client.return_value.chat.return_value={'message': {'content': "I'm doing well. How can I help?"}}
            result=process_request('How r u?')
        self.assertEqual(result.intent, Intent.CHAT)
        self.assertEqual(result.message, "I'm doing well. How can I help?")
        self.assertEqual(client.return_value.chat.call_args.kwargs['messages'][-1]['content'], 'How r u?')
    def test_no_raw_text_sent(self):
        marker=secrets.token_hex(20)
        _,client=self.classify("install "+marker,AgentResponse(intent=Intent.CHAT,message="hi"))
        self.assertNotIn(marker,str(client.return_value.chat.call_args))
    def test_bad_response_and_offline(self):
        with patch("agent.ollama.Client") as client:
            client.return_value.chat.return_value={"message":{"content":"invalid JSON"}}
            with self.assertRaises(RuntimeError): process_request("change password")
            client.return_value.chat.side_effect=ConnectionError()
            with self.assertRaises(RuntimeError): process_request("change password")
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

    def test_model_client_pool_is_reused_and_closed(self):
        with patch('agent.ollama.Client') as client:
            first = get_model_client()
            self.assertIs(first, get_model_client())
            client.assert_called_once()
            close_model_client()
            first.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
