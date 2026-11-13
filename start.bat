@echo off
setlocal

cd /d "%~dp0"
set "SIMULATION_API_KEY=dev-api-key"

echo Starting Ollama...
start "Ollama" /b ollama serve

timeout /t 2 /nobreak >nul

echo Starting simulation API on http://127.0.0.1:8000 ...
start "HR Simulation API" cmd /k "py -m uvicorn Simulations.api:app --host 127.0.0.1 --reload --port 8000"

echo Starting Streamlit on http://localhost:8501 ...
start "Project" cmd /k "py -m streamlit run Linear_Architecture\app.py"

echo.
echo Services started:
echo   Ollama:         http://127.0.0.1:11434
echo   Simulation API: http://127.0.0.1:8000
echo   Streamlit:      http://localhost:8501
echo.
pause