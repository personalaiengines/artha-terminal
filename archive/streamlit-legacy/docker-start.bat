@echo off
REM ============================================
REM ARTHA Terminal - Docker Quick Start (Windows)
REM ============================================

echo ARTHA Terminal - Docker Setup
echo ==============================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running. Please start Docker Desktop.
    pause
    exit /b 1
)

echo [1/4] Building Docker image...
docker build -t artha-terminal .

echo.
echo [2/4] Starting services...
docker compose up -d

echo.
echo [3/4] Waiting for app to be ready...
timeout /t 10 /nobreak >nul

echo.
echo [4/4] Opening browser...
start http://localhost:8501

echo.
echo ============================================
echo ARTHA Terminal is running!
echo.
echo Access the app at: http://localhost:8501
echo View logs: docker compose logs -f
echo Stop: docker compose down
echo ============================================
echo.
pause