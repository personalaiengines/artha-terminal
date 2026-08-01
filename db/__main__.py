"""Make `python -m db` create/migrate the schema, as the docs have always said.

db/ is a package, so the `if __name__ == "__main__"` guard in __init__.py only
ever fired for `python db/__init__.py`. `python -m db` — the documented setup
step — died with "'db' is a package and cannot be directly executed", which is
easy to miss when the next step appears to work anyway (init_database() also
runs lazily on first connection).
"""

from pathlib import Path

from db import get_connection, init_database


def main() -> None:
    # ARTHA_DB_PATH is how compose points the container at its volume.
    import os

    env_path = os.getenv("ARTHA_DB_PATH")
    db_path = init_database(Path(env_path)) if env_path else init_database()

    with get_connection(Path(db_path)) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    print(f"Database ready at: {db_path}")
    print(f"Tables ({len(tables)}): {', '.join(tables)}")


if __name__ == "__main__":
    main()
