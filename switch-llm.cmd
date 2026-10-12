@echo off
rem Double-click: switch the chat LLM server between Ollama and vLLM.
rem From a terminal you can also give a server: switch-llm.cmd vllm, switch-llm.cmd ollama, or switch-llm.cmd status
cd /d "%~dp0"
if "%~1"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\llm.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\llm.ps1" -Use %1
)
echo.
pause
