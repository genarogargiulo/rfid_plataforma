@echo off
:: ═════════════════════════════════════════════════════════════════════════
::  service_uninstall.bat — Detiene y elimina el servicio Windows.
::  Llamado automáticamente por el desinstalador de Inno Setup.
:: ═════════════════════════════════════════════════════════════════════════
setlocal

set "WINSW=%~dp0rfid_plataforma_svc.exe"

echo [service_uninstall] Deteniendo servicio...
"%WINSW%" stop >nul 2>&1
timeout /t 5 /nobreak >nul

echo [service_uninstall] Desinstalando servicio...
"%WINSW%" uninstall >nul 2>&1

echo [service_uninstall] Listo.
exit /b 0
