"""
Row counts for every table, plus which database file answered.

Which file that is matters more than it sounds: the container reads
/data/db/artha.db from the artha-db volume, anything on the host reads the
repo's db/artha.db, and the two hold different data. Printing the path means a
surprising row count is self-diagnosing.

    docker compose exec api python scripts/db_status.py     # the live one
    python scripts/db_status.py                             # the dev copy
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import get_connection


def main() -> None:
    with get_connection() as conn:
        path = conn.execute("PRAGMA database_list").fetchone()[2]
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        print(f"{path}\n")
        for t in tables:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t:<20} {n:>9,} rows")


if __name__ == "__main__":
    main()
