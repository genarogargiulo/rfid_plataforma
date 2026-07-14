@echo off
:: ═════════════════════════════════════════════════════════════════════════
::  service_install.bat — Registra FPT RFID Plataforma como servicio Windows
::  usando WinSW (Windows Service Wrapper).
::
::  Argumentos:
::    %1  Directorio de instalación  (ej: "C:\PLATAFORMA_RFID")
::
::  Uso manual (como Administrador):
::    service_install.bat "C:\PLATAFORMA_RFID"
::
::  Todo el detalle de la ejecución queda registrado en:
::    <directorio de instalación>\logs\service_install.log
:: ═════════════════════════════════════════════════════════════════════════
setlocal EnableDelayedExpansion

set "INSTALL_DIR=%~1"
if "%INSTALL_DIR%"=="" set "INSTALL_DIR=%~dp0"
if "%INSTALL_DIR:~-1%"=="\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"

if not exist "%INSTALL_DIR%\logs" mkdir "%INSTALL_DIR%\logs" >nul 2>&1
set "LOG=%INSTALL_DIR%\logs\service_install.log"

call :log "============================================================"
call :log "[%DATE% %TIME%] service_install.bat iniciado"
call :log "Directorio de instalacion: %INSTALL_DIR%"

set "WINSW=%INSTALL_DIR%\rfid_plataforma_svc.exe"
call :log "Ejecutable WinSW: %WINSW%"

:: Verificar que WinSW existe (si el antivirus lo bloqueo/elimino, se detecta aca)
if not exist "%WINSW%" (
    call :log "[ERROR] No se encontro rfid_plataforma_svc.exe en: %INSTALL_DIR%"
    call :log "        Causa probable: el antivirus lo elimino o bloqueo al extraerlo."
    call :log "        Solucion: agregar una exclusion de antivirus para la carpeta"
    call :log "        de instalacion y volver a ejecutar este script como administrador."
    exit /b 1
)

:: Verificar que el ejecutable de la app existe
if not exist "%INSTALL_DIR%\rfid_plataforma.exe" (
    call :log "[ERROR] No se encontro rfid_plataforma.exe en: %INSTALL_DIR%"
    exit /b 1
)

:: Desinstalar servicio anterior si existía (actualización in-place)
"%WINSW%" status >>"%LOG%" 2>&1
if not errorlevel 1 (
    call :log "[INFO] Servicio existente encontrado. Deteniendolo..."
    "%WINSW%" stop >>"%LOG%" 2>&1
    timeout /t 5 /nobreak >nul
    call :log "[INFO] Desinstalando version anterior..."
    "%WINSW%" uninstall >>"%LOG%" 2>&1
)

:: Instalar el servicio
call :log "[INFO] Instalando servicio Windows..."
"%WINSW%" install >>"%LOG%" 2>&1
if errorlevel 1 (
    call :log "[ERROR] No se pudo instalar el servicio (codigo %ERRORLEVEL%)."
    call :log "        Revisar permisos de administrador y que el antivirus no"
    call :log "        haya bloqueado rfid_plataforma_svc.exe."
    exit /b 1
)
call :log "[OK] Servicio registrado."

:: Iniciar el servicio
call :log "[INFO] Iniciando servicio..."
"%WINSW%" start >>"%LOG%" 2>&1
if errorlevel 1 (
    call :log "[ADVERTENCIA] El servicio fue instalado pero no pudo iniciarse ahora."
    call :log "              Verificar config.py con la conexion a SQL Server e iniciar"
    call :log "              manualmente: rfid_plataforma_svc.exe start"
) else (
    call :log "[OK] Servicio iniciado. Panel disponible en http://localhost:5000"
)

call :log "[%DATE% %TIME%] service_install.bat finalizado (exito)"
exit /b 0

:log
echo %~1
echo %~1>>"%LOG%"
exit /b 0
