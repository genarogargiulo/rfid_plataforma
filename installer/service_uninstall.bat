@echo off
:: ═════════════════════════════════════════════════════════════════════════
::  service_uninstall.bat — Detiene y elimina el servicio Windows.
::  Llamado automáticamente por el desinstalador de Inno Setup.
:: ═════════════════════════════════════════════════════════════════════════
setlocal

set "INSTALL_DIR=%~dp0"
if "%INSTALL_DIR:~-1%"=="\" set "INSTALL_DIR=%INSTALL_DIR:~0,-1%"
set "WINSW=%INSTALL_DIR%\rfid_plataforma_svc.exe"
if not exist "%INSTALL_DIR%\logs" mkdir "%INSTALL_DIR%\logs" >nul 2>&1
set "LOG=%INSTALL_DIR%\logs\service_install.log"

echo [%DATE% %TIME%] service_uninstall.bat iniciado>>"%LOG%"

echo [service_uninstall] Deteniendo servicio...
echo [service_uninstall] Deteniendo servicio...>>"%LOG%"
"%WINSW%" stop >>"%LOG%" 2>&1
timeout /t 5 /nobreak >nul

echo [service_uninstall] Desinstalando servicio...
echo [service_uninstall] Desinstalando servicio...>>"%LOG%"
"%WINSW%" uninstall >>"%LOG%" 2>&1

echo [service_uninstall] Listo.
echo [service_uninstall] Listo.>>"%LOG%"
exit /b 0
