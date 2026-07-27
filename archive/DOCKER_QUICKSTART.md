# ============================================
# ARTHA Terminal - Docker Quick Start
# ============================================

# 1. Build the image
docker build -t artha-terminal .

# 2. Start with docker-compose (recommended)
docker compose up -d

# 3. View logs
docker compose logs -f

# 4. Access the app
# Open http://localhost:8501 in your browser

# 5. Initialize database (first time only)
docker compose exec artha python -m db

# 6. Stop the services
docker compose down

# 7. Stop and remove volumes (fresh start)
docker compose down -v

# 8. Run one-off commands
docker compose exec artha python -c "from db import get_db_status; print(get_db_status())"