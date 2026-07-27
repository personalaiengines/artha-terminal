# ============================================
# ARTHA Terminal - Docker Makefile
# ============================================
# Usage:
#   make build       - Build the Docker image
#   make up          - Start all services in background
#   make down        - Stop all services
#   make restart     - Restart all services
#   make logs        - Tail container logs
#   make shell       - Open a bash shell inside the container
#   make init-db     - Initialize/reset the database
#   make test        - Run tests inside the container
#   make clean       - Remove all containers and volumes

.PHONY: build up down restart logs shell init-db test clean

# Default target
build:
	docker build -t artha-terminal .

up:
	docker compose up -d

down:
	docker compose down

restart: down up

logs:
	docker compose logs -f

shell:
	docker compose exec artha sh

init-db:
	docker compose exec artha python -c "from db import init_database; init_database()"

test:
	docker compose exec artha pytest tests/ -v

clean:
	docker compose down -v
	docker rmi artha-terminal 2>/dev/null || true

# Build with no cache (fresh install)
rebuild:
	docker compose down -v
	docker build --no-cache -t artha-terminal .
	docker compose up -d

# One-shot ingestion of symbols + prices + fundamentals
ingest:
	docker compose exec artha python scripts/ingest_all.py

# Run full ingestion (same as 'ingest')
populate: ingest

# Inspect database
db-status:
	docker compose exec artha python -c "
from db import get_db_connection
with get_db_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")
    tables = cursor.fetchall()
    print('Tables:', [t[0] for t in tables])
    for t in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {t[0]}')
        print(f'  {t[0]}: {cursor.fetchone()[0]} rows')
"