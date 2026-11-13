@echo off
setlocal
title Reiniciar Rotacion FastAPI

rem Reinicia SOLO el backend de Rotacion, igual que el paso [8/12] del .bat de servicios IAN
rem (misma carpeta, mismo puerto 5202 y mismo archivo rotacion.pid), sin tocar los demas servicios.

set "ROTACION_DIR=C:\Users\Administrator\Documents\servicios IAN\rotacion"
set "ROTACION_PYTHON=%ROTACION_DIR%\backend\.venv\Scripts\python.exe"
set "PID_DIR=C:\Users\Administrator\Documents\servicios IAN\pids"
set "ROTACION_PORT=5202"

if not exist "%ROTACION_PYTHON%" (
    echo ERROR: No existe %ROTACION_PYTHON%
    pause
    exit /b 1
)
if not exist "%ROTACION_DIR%\.env" (
    echo ERROR: Falta el archivo .env en %ROTACION_DIR%
    pause
    exit /b 1
)
if not exist "%PID_DIR%" mkdir "%PID_DIR%"

echo Deteniendo Rotacion...
rem Se detiene por el .pid y ademas se libera el puerto: el python.exe del .venv deja un
rem proceso hijo que el .pid no cubre, y si sigue vivo el codigo nuevo no puede arrancar.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$pidFile='%PID_DIR%\rotacion.pid'; if (Test-Path $pidFile) { Stop-Process -Id ([int](Get-Content $pidFile)) -Force -ErrorAction SilentlyContinue; Remove-Item $pidFile -Force -ErrorAction SilentlyContinue }; Get-NetTCPConnection -LocalPort %ROTACION_PORT% -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo Iniciando Rotacion en 127.0.0.1:%ROTACION_PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$p=Start-Process -FilePath '%ROTACION_PYTHON%' -ArgumentList '-m','uvicorn','app.main:app','--app-dir','backend','--host','127.0.0.1','--port','%ROTACION_PORT%' -WorkingDirectory '%ROTACION_DIR%' -WindowStyle Hidden -PassThru; $p.Id | Set-Content '%PID_DIR%\rotacion.pid'"
timeout /t 5 /nobreak >nul

echo Comprobando...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-RestMethod 'http://127.0.0.1:%ROTACION_PORT%/health' -TimeoutSec 10; Write-Host ('OK: ' + ($r | ConvertTo-Json -Compress)) } catch { Write-Host 'ERROR: Rotacion no responde en el puerto %ROTACION_PORT%' }; try { $t = Invoke-RestMethod 'http://127.0.0.1:%ROTACION_PORT%/api/tiendas' -TimeoutSec 60; Write-Host ('Tiendas y bodegas: ' + @($t).Count) } catch { Write-Host 'AVISO: /api/tiendas no respondio (revisar conexion a SQL Server)' }"

echo.
pause
