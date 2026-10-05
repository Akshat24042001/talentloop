"""Copy every TalentLoop table from one Postgres database to another (for example from a Supabase project in Mumbai
to a new one in Singapore, next to the Render server).

    python scripts/move_database.py --source "postgresql://...mumbai..." --target "postgresql://...singapore..."

- Read-only on the source. Creates the tables on the target, then copies the rows in batches.
- Refuses to write into a target that already has TalentLoop data (add --force to copy into it anyway).
- Prints row counts for both sides at the end; they must match.
- Stop the app (or pause writes) while it runs, so nothing is written to the old database halfway through.
Files (resumes, recordings) live in Supabase Storage, not in the database: copy them with scripts/move_storage.py.
"""
import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pg(url: str) -> str:
    url = url.strip()
    for p in ("postgres://", "postgresql://"):
        if url.startswith(p):
            return "postgresql+psycopg://" + url[len(p):]
    return url


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="old database URL")
    ap.add_argument("--target", required=True, help="new database URL")
    ap.add_argument("--force", action="store_true", help="copy even if the target already has data")
    ap.add_argument("--batch", type=int, default=500)
    a = ap.parse_args()
    if pg(a.source) == pg(a.target):
        sys.exit("Source and target are the same database.")
    os.environ["DATABASE_URL"] = a.target                # backend.db builds its tables on this one
    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
    from sqlalchemy import create_engine, func, select
    from backend import db
    src = create_engine(pg(a.source), connect_args={"prepare_threshold": None})
    db.migrate()                                       # creates every table, index and column on the target
    tables = [t for t in db.Base.metadata.sorted_tables]  # parents before children (foreign keys)
    with db.engine.connect() as t:
        filled = [x.name for x in tables if t.execute(select(func.count()).select_from(x)).scalar()]
    if filled and not a.force:
        sys.exit(f"The target already has data in: {', '.join(filled)}. Use an empty database, or --force.")
    with src.connect() as s, db.engine.begin() as t:
        for table in tables:
            have = {c["name"] for c in __import__("sqlalchemy").inspect(src).get_columns(table.name)} if src.dialect.has_table(s, table.name) else set()
            if not have:
                print(f"  {table.name}: not in the source, skipped")
                continue
            cols = [c for c in table.c if c.name in have]
            n, batch = 0, []
            for row in s.execution_options(stream_results=True).execute(select(*cols)):
                batch.append(dict(row._mapping))
                if len(batch) >= a.batch:
                    t.execute(table.insert(), batch); n += len(batch); batch = []
            if batch:
                t.execute(table.insert(), batch); n += len(batch)
            print(f"  {table.name}: {n} rows")
    bad = []
    with src.connect() as s, db.engine.connect() as t:
        print("\nCheck (source / target):")
        for table in tables:
            if not src.dialect.has_table(s, table.name):
                continue
            a_n = s.execute(select(func.count()).select_from(table)).scalar()
            b_n = t.execute(select(func.count()).select_from(table)).scalar()
            print(f"  {table.name:24} {a_n:>8} {b_n:>8}{'' if a_n == b_n else '   MISMATCH'}")
            if a_n != b_n:
                bad.append(table.name)
    if bad:
        sys.exit(f"Row counts differ in: {', '.join(bad)}. Do not switch DATABASE_URL yet.")
    print("\nAll tables copied. Next: copy the files (scripts/move_storage.py), then point DATABASE_URL and S3_* on Render at the new project.")


if __name__ == "__main__":
    main()
