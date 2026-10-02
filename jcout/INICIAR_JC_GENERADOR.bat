@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo No existe el entorno virtual.
    echo Ejecuta primero INSTALAR_JC_GENERADOR.bat
    pause
    exit /b 1
)
.venv\Scripts\python.exe -m streamlit run app.py
pause
