@echo off
echo Starting LocalForge backend...
start "LocalForge Backend" cmd /k "py -3 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000"
timeout /t 2 /nobreak >nul
echo Starting LocalForge frontend...
start "LocalForge Frontend" cmd /k "cd frontend && npm run dev"
echo.
echo LocalForge is starting:
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo   API docs: http://localhost:8000/docs
