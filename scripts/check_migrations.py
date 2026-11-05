"""Check Alembic connectivity and show current migration revision."""
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from app.database import engine

config = Config('alembic.ini')
script = ScriptDirectory.from_config(config)
heads = set(script.get_heads())
with engine.connect() as connection:
    current = set(MigrationContext.configure(connection).get_current_heads())
print('Migration heads:', sorted(heads))
print('Database revisions:', sorted(current))
if current != heads:
    raise SystemExit('Database is not at migration head; review and run Alembic upgrade.')
print('Database migration revision is current.')
