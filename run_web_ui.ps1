Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir
uv run python scripts/web_ui_server.py
