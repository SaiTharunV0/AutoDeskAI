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
