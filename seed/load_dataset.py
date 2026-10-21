#!/usr/bin/env python3
"""
Load the LeaveFlow CSV dataset into PostgreSQL (one transaction, all-or-nothing).

Put this file next to the `leaveflow_dataset/` folder (e.g. in your `seed/` folder) and run it
from the PROJECT ROOT:

    python seed/load_dataset.py            # load into EMPTY tables
    python seed/load_dataset.py --reset    # wipe all LeaveFlow tables first, then load

It reads DATABASE_URL from your environment or from the .env file in the current folder.
Requires:  pip install psycopg2-binary python-dotenv   (you already have these for the app)
"""
import argparse
import csv
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import psycopg2

# Load order matters (parents before children). departments is handled specially.
ORDER = ["roles", "departments", "employees", "users", "leave_types", "holidays", "approval_rules",
         "system_settings", "leave_balances", "leave_requests", "approval_steps", "audit_logs", "notifications"]
SERIAL_TABLES = [t for t in ORDER if t != "system_settings"]
DEFAULT_URL = "postgresql+psycopg2://leaveflow:leaveflow@localhost:5432/leaveflow"


def clean_url(url):
    """SQLAlchemy URLs look like postgresql+psycopg2://...; psycopg2 wants postgresql://..."""
    parts = urlsplit(url)
    scheme = parts.scheme.split("+")[0]
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def csv_info(path):
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        n = sum(1 for _ in reader)
    return header, n


def copy_csv(cur, table, path, columns=None):
    header, _ = csv_info(path)
    cols = ", ".join(columns or header)
    with open(path, encoding="utf-8", newline="") as f:
        cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true)", f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(Path(__file__).resolve().parent / "leaveflow_dataset"),
                    help="folder that contains the CSV files")
    ap.add_argument("--reset", action="store_true", help="TRUNCATE all LeaveFlow tables before loading")
    a = ap.parse_args()

    data = Path(a.data_dir)
    missing = [t for t in ORDER if not (data / f"{t}.csv").exists()]
    if missing:
        sys.exit(f"Missing CSV files in {data}: {', '.join(m + '.csv' for m in missing)}")

    url = os.getenv("DATABASE_URL", DEFAULT_URL)
    try:
        conn = psycopg2.connect(clean_url(url))
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Could not connect to PostgreSQL. Is it running, and is DATABASE_URL correct?\n  {e}")
    conn.autocommit = False
    cur = conn.cursor()
    try:
        # 1. tables must exist
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        existing = {r[0] for r in cur.fetchall()}
        absent = [t for t in ORDER if t not in existing]
        if absent:
            sys.exit("These tables do not exist yet: " + ", ".join(absent) +
                     "\nCreate empty tables first:  python -m database.init_db   (WITHOUT --reset)")

        # 2. tables must be empty (or --reset)
        if a.reset:
            print("Wiping existing data ...")
            cur.execute("TRUNCATE TABLE " + ", ".join(ORDER) + " RESTART IDENTITY CASCADE")
        else:
            cur.execute("SELECT count(*) FROM employees")
            if cur.fetchone()[0] > 0:
                sys.exit("The database already contains data (e.g. the old demo seed).\n"
                         "Run again with --reset to wipe it and load this dataset.")

        # 3. load
        for t in ORDER:
            path = data / f"{t}.csv"
            if t == "departments":
                # departments.head_employee_id points at employees, which point back at departments.
                # So: insert departments without the head now, set the head after employees exist.
                cur.execute("CREATE TEMP TABLE dept_stage (id int, name text, head_employee_id int, "
                            "created_at timestamptz, updated_at timestamptz) ON COMMIT DROP")
                copy_csv(cur, "dept_stage", path)
                cur.execute("INSERT INTO departments (id, name, created_at, updated_at) "
                            "SELECT id, name, created_at, updated_at FROM dept_stage")
            else:
                copy_csv(cur, t, path)
            if t == "employees":
                cur.execute("UPDATE departments d SET head_employee_id = s.head_employee_id "
                            "FROM dept_stage s WHERE s.id = d.id")
            print(f"  loaded {t}")

        # 4. reset SERIAL sequences (ids were inserted explicitly)
        for t in SERIAL_TABLES:
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), COALESCE(MAX(id), 1), "
                        f"MAX(id) IS NOT NULL) FROM {t}")

        # 5. verify row counts against the CSV files
        print("\nVerification (CSV rows vs database rows):")
        ok = True
        for t in ORDER:
            _, n = csv_info(data / f"{t}.csv")
            cur.execute(f"SELECT count(*) FROM {t}")
            db = cur.fetchone()[0]
            flag = "OK" if db == n else "MISMATCH"
            ok &= db == n
            print(f"  {t:16s} {n:>9,} {db:>9,}  {flag}")
        if not ok:
            raise RuntimeError("Row counts do not match - rolled back.")
        conn.commit()
        print("\nDone. Dataset loaded and committed.")
        print("Start the app with:  streamlit run app.py   and sign in as employee / manager / hr")
    except SystemExit:
        conn.rollback()
        raise
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        sys.exit(f"\nLoad failed and was rolled back (nothing was changed).\n  {type(e).__name__}: {e}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()