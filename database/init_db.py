# """Database initialisation.

#     python -m database.init_db              # create tables if missing
#     python -m database.init_db --reset      # drop everything, recreate and seed demo data
#     python -m database.init_db --export-schema   # regenerate schema.sql from the models
# """
# import argparse
# from pathlib import Path

# from sqlalchemy.dialects import postgresql
# from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable, ForeignKeyConstraint

# from database import models
# from database.connection import get_engine

# SCHEMA_FILE = Path(__file__).resolve().parent.parent / "schema.sql"


# def create_all(engine=None) -> None:
#     models.Base.metadata.create_all(engine or get_engine())


# def drop_all(engine=None) -> None:
#     models.Base.metadata.drop_all(engine or get_engine())


# def export_schema() -> str:
#     """Render PostgreSQL DDL for all tables and indexes directly from the ORM metadata."""
#     dialect = postgresql.dialect()
#     parts = ["-- LeaveFlow PostgreSQL schema (generated from database/models.py)",
#              "-- Regenerate with: python -m database.init_db --export-schema", ""]
#     for table in models.Base.metadata.sorted_tables:
#         parts.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
#         for index in sorted(table.indexes, key=lambda i: i.name):
#             parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
#         parts.append("")
#     # Circular foreign keys (use_alter) are added after all tables exist.
#     for table in models.Base.metadata.sorted_tables:
#         for fk in table.constraints:
#             if isinstance(fk, ForeignKeyConstraint) and fk.use_alter:
#                 parts.append(str(AddConstraint(fk).compile(dialect=dialect)).strip() + ";")
#     return "\n".join(parts)


# def main() -> None:
#     parser = argparse.ArgumentParser(description="LeaveFlow database setup")
#     parser.add_argument("--reset", action="store_true", help="drop all tables, recreate and seed demo data")
#     parser.add_argument("--export-schema", action="store_true", help="write schema.sql")
#     args = parser.parse_args()

#     if args.export_schema:
#         SCHEMA_FILE.write_text(export_schema(), encoding="utf-8")
#         print(f"Wrote {SCHEMA_FILE}")
#         return
#     if args.reset:
#         drop_all()
#     create_all()
#     print("Tables created.")
#     if args.reset:
#         from seed.seed_data import seed_database
#         seed_database()
#         print("Demo data seeded.")


# if __name__ == "__main__":
#     main()
"""Database initialisation.

    python -m database.init_db              # create tables if missing
    python -m database.init_db --reset      # drop everything, recreate and seed demo data
    python -m database.init_db --export-schema   # regenerate schema.sql from the models
"""
import argparse
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable, ForeignKeyConstraint

from database import models
from database.connection import get_engine

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "schema.sql"


def create_all(engine=None) -> None:
    models.Base.metadata.create_all(engine or get_engine())


def drop_all(engine=None) -> None:
    models.Base.metadata.drop_all(engine or get_engine())


def export_schema() -> str:
    """Render PostgreSQL DDL for all tables and indexes directly from the ORM metadata."""
    dialect = postgresql.dialect()
    parts = ["-- LeaveFlow PostgreSQL schema (generated from database/models.py)",
             "-- Regenerate with: python -m database.init_db --export-schema", ""]
    for table in models.Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name):
            parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        parts.append("")
    # Circular foreign keys (use_alter) are added after all tables exist.
    for table in models.Base.metadata.sorted_tables:
        for fk in table.constraints:
            if isinstance(fk, ForeignKeyConstraint) and fk.use_alter:
                parts.append(str(AddConstraint(fk).compile(dialect=dialect)).strip() + ";")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="LeaveFlow database setup")
    parser.add_argument("--reset", action="store_true", help="drop all tables, recreate and seed demo data")
    parser.add_argument("--export-schema", action="store_true", help="write schema.sql")
    args = parser.parse_args()

    if args.export_schema:
        SCHEMA_FILE.write_text(export_schema(), encoding="utf-8")
        print(f"Wrote {SCHEMA_FILE}")
        return
    if args.reset:
        drop_all()
    create_all()
    print("Tables created.")
    if args.reset:
        from seed.seed_data import seed_database
        seed_database()
        print("Demo data seeded.")


if __name__ == "__main__":
    from sqlalchemy.exc import OperationalError
    try:
        main()
    except OperationalError as exc:
        reason = str(exc.orig).strip().splitlines()[-1] if exc.orig else "connection failed"
        raise SystemExit(
            f"\nCould not connect to PostgreSQL: {reason}\n"
            "Check DATABASE_URL in your .env file (user, password, host, port, database name), that the database exists, "
            "and that the PostgreSQL service is running. See README section 12 (Database setup).")