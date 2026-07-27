#!/bin/bash
# ============================================
# ARTHA Terminal - Database Initialization
# Run this inside the container to initialize the DB
# --------------------------------------------
# Example: docker exec -it artha-terminal python scripts/init_db.sh
# ============================================

set -e

echo "🔧 Initializing ARTHA Terminal Database..."

# Check if schema exists
if [ -f "/app/db/schema.sql" ]; then
    echo "✅ Schema found"
else
    echo "❌ Schema not found at /app/db/schema.sql"
    exit 1
fi

# Initialize SQLite database
python -c "
from db import init_database
print('📦 Creating database tables...')
init_database()
print('✅ Database initialized successfully!')
"

# Display schema info
echo ""
echo "📊 Database Status:"
python -c "
from db import get_db_connection
conn = get_db_connection()
cursor = conn.cursor()

# List tables
cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table';\")
tables = cursor.fetchall()
print(f'   Tables: {[t[0] for t in tables]}')

# Count records
for table in ['symbols', 'ohlcv_candles', 'fundamentals']:
    try:
        cursor.execute(f'SELECT COUNT(*) FROM {table}')
        count = cursor.fetchone()[0]
        print(f'   {table}: {count} records')
    except:
        print(f'   {table}: N/A')

conn.close()
"

echo ""
echo "🎉 Database ready! You can now run the Streamlit app."