from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import DATABASE_URL
engine = create_engine(DATABASE_URL, pool_pre_ping=True,
    connect_args={'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
class Base(DeclarativeBase):
    pass
def upgrade_user_profile(db_engine=engine):
    """Add registration fields to existing installations without changing user IDs."""
    existing = {column['name'] for column in inspect(db_engine).get_columns('users')}
    columns = {
        'first_name': 'VARCHAR(50)',
        'last_name': 'VARCHAR(50)',
        'date_of_birth': 'DATE',
        'username': 'VARCHAR(50)',
    }
    with db_engine.begin() as connection:
        for name, column_type in columns.items():
            if name not in existing:
                connection.execute(text(f'ALTER TABLE users ADD COLUMN {name} {column_type}'))
        connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)'))

def get_db():
    with SessionLocal() as db:
        yield db

def upgrade_query_indexes(db_engine=engine):
    """create_all does not add new indexes to tables in an existing installation."""
    names = {"ix_devices_owner", "ix_devices_token", "ix_requests_user_id",
             "ix_tasks_status_created", "ix_tasks_device_status", "ix_audit_resource"}
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            if index.name in names:
                index.create(db_engine, checkfirst=True)

def upgrade_application_access(db_engine=engine):
    """Add catalog and request lifecycle fields without replacing existing records."""
    additions = {
        'application_policies': {
            'display_name': "VARCHAR(100) NOT NULL DEFAULT ''",
            'description': "VARCHAR(500) NOT NULL DEFAULT ''",
            'requestable_roles_json': "VARCHAR(1000) NOT NULL DEFAULT '[\"viewer\"]'",
            'allowed_groups_json': "VARCHAR(1000) NOT NULL DEFAULT '[]'",
            'default_duration_days': 'INTEGER NOT NULL DEFAULT 30',
            'max_duration_days': 'INTEGER NOT NULL DEFAULT 90',
            'approval_mode': "VARCHAR(30) NOT NULL DEFAULT 'ADMIN_ONLY'",
            'conditions_json': "VARCHAR(2000) NOT NULL DEFAULT '{}'",
            'fallback': "VARCHAR(40) NOT NULL DEFAULT 'REQUIRE_ADMIN_APPROVAL'",
            'human_roles_json': "VARCHAR(1000) NOT NULL DEFAULT '[]'",
            'risk': "VARCHAR(20) NOT NULL DEFAULT 'LOW'",
            'provider_type': "VARCHAR(20) NOT NULL DEFAULT 'MOCK'",
            'config_ref': "VARCHAR(100) NOT NULL DEFAULT ''",
            'auto_allowed': 'BOOLEAN NOT NULL DEFAULT FALSE',
            'version': 'INTEGER NOT NULL DEFAULT 1',
            'updated_at': 'TIMESTAMP',
        },
        'access_requests': {
            'requested_role': "VARCHAR(50) NOT NULL DEFAULT 'viewer'",
            'justification': "VARCHAR(500) NOT NULL DEFAULT ''",
            'duration_days': 'INTEGER NOT NULL DEFAULT 30',
            'approval_route': "VARCHAR(40) NOT NULL DEFAULT 'ADMIN'",
            'policy_version': 'INTEGER NOT NULL DEFAULT 1',
            'evaluation_json': "VARCHAR(4000) NOT NULL DEFAULT '{}'",
            'provisioning_status': "VARCHAR(40) NOT NULL DEFAULT 'NOT_STARTED'",
            'expires_at': 'TIMESTAMP',
            'approver_id': 'INTEGER',
            'decision_at': 'TIMESTAMP',
            'provisioned_at': 'TIMESTAMP',
            'provision_attempts': 'INTEGER NOT NULL DEFAULT 0',
            'last_provision_attempt_at': 'TIMESTAMP',
        },
        'helpdesk_requests': {
            'resolved': 'BOOLEAN',
            'resolution_reporter': 'VARCHAR(20)',
            'rejection_source': 'VARCHAR(20)',
            'resolution_attempts': 'INTEGER NOT NULL DEFAULT 0',
        },
    }
    with db_engine.begin() as connection:
        for table, columns in additions.items():
            existing = {column['name'] for column in inspect(connection).get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
        connection.execute(text("UPDATE application_policies SET display_name = 'Tableau (example)' WHERE key = 'tableau' AND display_name = ''"))
        connection.execute(text("UPDATE application_policies SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
        request_columns = {column['name'] for column in inspect(connection).get_columns('helpdesk_requests')}
        if {'status', 'message'} <= request_columns:
            connection.execute(text("""UPDATE helpdesk_requests SET rejection_source =
                CASE WHEN EXISTS (SELECT 1 FROM access_requests
                    WHERE access_requests.request_id = helpdesk_requests.id
                    AND access_requests.status = 'REJECTED'
                    AND access_requests.approver_id IS NOT NULL)
                THEN 'ADMIN' ELSE 'AUTODESKAI' END
                WHERE status = 'CLOSED' AND rejection_source IS NULL
                AND message LIKE '%I have closed this ticket; no confirmation is needed.%'"""))
