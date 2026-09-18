"""Step 6: every mapped model column against the migrated schema. Runs inside the API container."""
import sys

sys.path.insert(0, "/app")

from sqlalchemy import inspect  # noqa: E402

import models  # noqa: E402, F401
from database import Base, engine  # noqa: E402

inspector = inspect(engine)
problems, notes = [], []


def python_type(column_type):
    try:
        return column_type.python_type
    except NotImplementedError:
        return None


for table in Base.metadata.sorted_tables:
    if not inspector.has_table(table.name):
        problems.append(f"{table.name}: table not in the database")
        continue
    db_columns = {c["name"]: c for c in inspector.get_columns(table.name)}
    db_pk = set(inspector.get_pk_constraint(table.name)["constrained_columns"])
    model_pk = {c.name for c in table.primary_key.columns}
    if db_pk != model_pk:
        problems.append(f"{table.name}: primary key {sorted(model_pk)} in the model, {sorted(db_pk)} in the database")
    for column in table.columns:
        db = db_columns.get(column.name)
        if db is None:
            problems.append(f"{table.name}.{column.name}: not in the database")
            continue
        if python_type(column.type) != python_type(db["type"]):
            problems.append(f"{table.name}.{column.name}: {column.type} in the model, {db['type']} in the database")
        for attribute in ("length", "precision", "scale"):
            model_value, db_value = getattr(column.type, attribute, None), getattr(db["type"], attribute, None)
            if model_value is not None and model_value != db_value:
                problems.append(f"{table.name}.{column.name}: {attribute} {model_value} in the model, {db_value} in the database")
        if column.nullable is False and db["nullable"] and column.name not in model_pk:
            notes.append(f"{table.name}.{column.name}: NOT NULL in the model only")
    unmapped = sorted(set(db_columns) - {c.name for c in table.columns})
    if unmapped:
        notes.append(f"{table.name}: database columns not mapped {unmapped}")
    for fk in table.foreign_keys:
        target = fk.target_fullname.split(".")[0]
        db_targets = {f["referred_table"] for f in inspector.get_foreign_keys(table.name)}
        if target not in db_targets:
            problems.append(f"{table.name}: foreign key to {target} in the model only")

print(f"mapped tables: {[t.name for t in Base.metadata.sorted_tables]}")
print(f"database tables not mapped: {sorted(set(inspector.get_table_names()) - set(Base.metadata.tables))}")
for note in notes:
    print("note:", note)
print(f"{'ok  ' if not problems else 'FAIL'} model and schema mismatches: {len(problems)}")
for problem in problems:
    print("   ", problem)
sys.exit(1 if problems else 0)
