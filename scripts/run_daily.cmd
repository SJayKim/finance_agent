@echo off
REM finance_agent daily job body. Called by Task Scheduler (via schedule_daily.cmd)
REM or run manually. Project root is derived from this script's location, so there is
REM no hardcoded path. Appends stdout/stderr to logs\daily.log.
setlocal
set "PROJ=%~dp0.."
cd /d "%PROJ%" || exit /b 1
if not exist "logs" mkdir "logs"
uv run python -m app.runner >> "logs\daily.log" 2>&1
