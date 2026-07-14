@echo off
:: ═════════════════════════════════════════════════════════════════════════
::  resetear_password.bat — Restablece la contraseña de un usuario cuando
::  se perdió el acceso al panel web. Requiere que la base de datos
::  configurada en config.py esté accesible.
:: ═════════════════════════════════════════════════════════════════════════
title Resetear contraseña - Plataforma RFID
cd /d "%~dp0"
rfid_plataforma.exe reset-admin-password
echo.
pause
