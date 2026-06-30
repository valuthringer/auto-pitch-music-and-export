@echo off
title Auto Pitch Export
cd /d "%~dp0"

REM --- Check that Python is available ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python introuvable dans le PATH.
    echo Installe Python depuis https://www.python.org/downloads/ puis reessaie.
    echo.
    pause
    exit /b 1
)

REM --- Install Streamlit if missing ---
python -m streamlit version >nul 2>&1
if errorlevel 1 (
    echo Installation de Streamlit en cours...
    python -m pip install streamlit
    echo.
)

REM --- Launch the app (opens in the browser) ---
echo Lancement de Auto Pitch Export...
echo Ferme cette fenetre pour arreter l'application.
echo.
python -m streamlit run pitch_app.py

pause
