"""One-time inventory and transactional clear of app tables and their IDs."""
import sys
from sqlalchemy import inspect, text
from app.database import engine
from app import models  # noqa: F401 - populate mapped table metadata

expected = set(models.Base.metadata.tables)
with engine.connect() as connection:
    actual = set(inspect(connection).get_table_names(schema="public"))
    print("Public tables:", sorted(actual))
    print("App tables:", sorted(expected))
    if actual != expected:
        raise SystemExit("Public tables differ from app tables; stopped without changes")
    counts = {name: connection.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one()
              for name in sorted(actual)}
    print("Rows before:", counts)

if "--delete" not in sys.argv:
    raise SystemExit(0)

with engine.begin() as connection:
    names = ", ".join(f'public."{name}"' for name in sorted(actual))
    connection.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY"))

with engine.connect() as connection:
    after = {name: connection.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one()
             for name in sorted(actual)}
print("Rows after:", after)
if any(after.values()):
    raise SystemExit("Verification failed: some rows remain")
