@echo off
:: ═════════════════════════════════════════════════════════════════════════
::  service_install.bat — Registra FPT RFID Plataforma como servicio Windows
::  usando WinSW (Windows Service Wrapper).
::
::  Argumentos:
::    %1  Directorio de instalación  (ej: "C:\Program Files\FPT RFID Plataforma")
::    %2  Nombre del servicio (no usado directamente, definido en el XML)
::
::  Uso manual (como Administrador):
::    service_install.bat "C:\FPT_RFID"
:: ═════════════════════════════════════════════════════════════════════════
setlocal EnableDelayedExpansion

set "INSTALL_DIR=%~1"
if "%INSTALL_DIR%"=="" set "INSTALL_DIR=%~dp0"

:: Eliminar barra final si la hubiera
if "%INSTALL_DIR:~-1%"=="\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"

set "WINSW=%INSTALL_DIR%\rfid_plataforma_svc.exe"

echo.
echo [service_install] Directorio : %INSTALL_DIR%
echo [service_install] WinSW      : %WINSW%
echo.

:: Verificar que WinSW existe
if not exist "%WINSW%" (
    echo [ERROR] No se encontro rfid_plataforma_svc.exe en: %INSTALL_DIR%
    exit /b 1
)

:: Verificar que el ejecutable de la app existe
if not exist "%INSTALL_DIR%\rfid_plataforma.exe" (
    echo [ERROR] No se encontro rfid_plataforma.exe en: %INSTALL_DIR%
    exit /b 1
)

:: Crear directorio de logs
if not exist "%INSTALL_DIR%\logs" mkdir "%INSTALL_DIR%\logs"

:: Desinstalar servicio anterior si existía (actualización in-place)
"%WINSW%" status >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Servicio existente encontrado. Deteniendolo...
    "%WINSW%" stop >nul 2>&1
    timeout /t 5 /nobreak >nul
    echo [INFO] Desinstalando version anterior...
    "%WINSW%" uninstall
)

:: Instalar el servicio
echo [INFO] Instalando servicio Windows...
"%WINSW%" install
if errorlevel 1 (
    echo [ERROR] No se pudo instalar el servicio.
    exit /b 1
)

:: Iniciar el servicio
echo [INFO] Iniciando servicio...
"%WINSW%" start
if errorlevel 1 (
    echo [ADVERTENCIA] El servicio fue instalado pero no pudo iniciarse ahora.
    echo               Verificar config.py con la conexion a SQL Server e iniciar
    echo               manualmente: rfid_plataforma_svc.exe start
) else (
    echo [OK] Servicio iniciado. Panel disponible en http://localhost:5000
)

echo.
exit /b 0
