@echo off
cd /d "%~dp0"
echo ============================================
echo   JC GENERADOR DE CODIGOS - INSTALADOR
echo ============================================
if not exist .venv (
    echo Creando entorno virtual...
    py -m venv .venv
    if errorlevel 1 python -m venv .venv
)
echo Actualizando pip...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 pause & exit /b 1
echo Instalando dependencias...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR instalando dependencias.
    pause
    exit /b 1
)
echo.
echo INSTALACION COMPLETADA.
echo Ahora ejecuta INICIAR_JC_GENERADOR.bat
pause
