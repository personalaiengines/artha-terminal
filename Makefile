# ============================================
# ARTHA Terminal - Docker Makefile
# ============================================
# Services are `api` (Starlette, :8000) and `web` (Next.js, :3000).
# There is no service called `artha` — that was the single-container Streamlit
# era, and every target here used to point at it, so none of them ran.
#
#   make up          - Start both services
#   make down        - Stop (the database volume survives)
#   make build       - Rebuild both images
#   make build-api   - Rebuild just the API (after a Python change)
#   make build-web   - Rebuild just the UI (after a web/ change)
#   make logs        - Tail both; logs-api / logs-web for one
#   make shell       - Shell inside the API container
#   make test        - Run pytest inside the API container
#   make ingest      - One-shot symbol + price + fundamentals ingestion
#   make db-status   - Row counts for every table in the LIVE database
#   make init-db     - Create/migrate the schema
#   make clean       - down -v + remove images  (DESTROYS the database)

.PHONY: build build-api build-web up down restart logs logs-api logs-web \
        shell test init-db db-status ingest populate clean rebuild

build:
	docker compose build

build-api:
	docker compose build api && docker compose up -d api

build-web:
	docker compose build web && docker compose up -d web

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

logs-web:
	docker compose logs -f web

shell:
	docker compose exec api sh

# `exec api pytest tests/` cannot work: the production image deliberately omits
# tests/ (Dockerfile copies only config/db/ingestion/engines/agent/services/api/
# scripts). So mount the suite read-only into a throwaway container instead.
# MSYS_NO_PATHCONV + `pwd -W` keep Git Bash on Windows from mangling both sides
# of the -v argument; both are harmless on Linux and macOS.
# test_news_degraded still fails here — it reads web/, which is not in this image.
test:
	MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps \
		-v "$$(pwd -W 2>/dev/null || pwd)/tests:/app/tests:ro" \
		--entrypoint pytest api tests/ -q

init-db:
	docker compose exec api python -c "from db import init_database; print(init_database())"

ingest:
	docker compose exec api python scripts/ingest_all.py

populate: ingest

# Row counts for the volume-backed database the app actually reads,
# not the repo's db/artha.db. Prints which file answered.
db-status:
	docker compose exec api python scripts/db_status.py

# Destroys the database volume.
clean:
	docker compose down -v
	-docker rmi artha-api artha-web 2>/dev/null

rebuild:
	docker compose build --no-cache
	docker compose up -d
