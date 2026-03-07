@echo off
echo Stopping existing LocalForge processes...

:: Kill any uvicorn process on port 8000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo Killing PID %%a on port 8000
    taskkill /PID %%a /F >nul 2>&1
)

:: Kill any vite/node process on port 5173
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    echo Killing PID %%a on port 5173
    taskkill /PID %%a /F >nul 2>&1
)

:: Also close any open LocalForge console windows by title
taskkill /FI "WINDOWTITLE eq LocalForge Backend" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq LocalForge Frontend" /F >nul 2>&1

timeout /t 1 /nobreak >nul

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
