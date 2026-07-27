#!/bin/bash
# ============================================
# ARTHA Terminal - Entrypoint Script
# Handles DB initialization on first run
# ============================================

set -e

# Database path (use env var or default to volume-mounted path)
DB_PATH="${ARTHA_DB_PATH:-/data/db/artha.db}"

echo "🔧 ARTHA Terminal Starting..."
echo "   Database path: ${DB_PATH}"

# Create database directory if it doesn't exist
DB_DIR=$(dirname "${DB_PATH}")
mkdir -p "${DB_DIR}"

# init_database() is idempotent (CREATE TABLE IF NOT EXISTS + idempotent
# migrations), so run it on every start. Running it only on first run would
# leave existing volumes without columns added to the schema later.
if [ ! -f "${DB_PATH}" ]; then
    echo "⚡ First-run detected - initializing database..."
else
    echo "🔎 Database exists - applying any pending migrations..."
fi

python -c "
import sys
sys.path.insert(0, '/app')
from db import init_database
from pathlib import Path
init_database(Path('${DB_PATH}'))
"
echo "✅ Database ready at ${DB_PATH}"

# Show database status
python -c "
import sys
sys.path.insert(0, '/app')
from pathlib import Path
db_path = Path('${DB_PATH}')
if db_path.exists():
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")
    tables = [t[0] for t in cursor.fetchall()]
    print(f'   Tables: {tables}')
    conn.close()
"

# Execute the main command
echo "🚀 Starting Streamlit server..."
exec "$@"