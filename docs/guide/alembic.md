# Alembic integration

OneAdmin ships its own migrations for its tables:
- they are applied by `oneadmin migrate`
- they are tracked in a separate version table, `oneadmin_alembic_version`
- they never touch your migration history

## The one required change
Alembic autogenerate proposes **dropping every table it doesn't find in your metadata**, and once `oneadmin migrate` has run, that includes OneAdmin's tables. Tell your `alembic/env.py` to ignore them:

```python
from oneadmin.alembic import include_object

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
```

Pass it in `run_migrations_offline()` too.

If you already have an `include_object`, combine the two:
```python
from oneadmin.alembic import is_oneadmin_object

def include_object(obj, name, type_, reflected, compare_to):
    if is_oneadmin_object(name, type_):
        return False
    return my_existing_rules(obj, name, type_, reflected, compare_to)
```

Verify it with `alembic check`, which should report "No new upgrade operations detected".

## Deploying
Run both migration streams, in either order:
```bash
alembic upgrade head
oneadmin migrate
```
