@echo off
REM Register the finance_agent daily run with Windows Task Scheduler (daily 06:40).
REM Task Scheduler uses the OS LOCAL timezone -- if this PC is KST, this is 06:40 KST.
REM Path is derived from this script's location (no hardcoded path). The task invokes
REM run_daily.cmd (job body) so the schtasks /TR has no nested redirection to break.
setlocal
set "RUNNER=%~dp0run_daily.cmd"
schtasks /Create /TN "finance_agent_daily" /SC DAILY /ST 06:40 /F /TR "cmd /c \"%RUNNER%\""
if %errorlevel%==0 (
  echo [ok] finance_agent_daily registered ^(daily 06:40 local TZ^).
  echo      Verify once: schtasks /Run /TN finance_agent_daily
  echo      Remove:      schtasks /Delete /TN finance_agent_daily /F
) else (
  echo [error] registration failed ^(errorlevel %errorlevel%^). Try again in an elevated cmd.
)
