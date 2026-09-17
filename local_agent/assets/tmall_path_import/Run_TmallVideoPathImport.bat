@echo off
chcp 65001 >nul
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%PS%" -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0TmallVideoPathImport.ps1"
if errorlevel 1 (
  echo.
  echo 导入失败。按任意键关闭窗口。
  pause >nul
)
