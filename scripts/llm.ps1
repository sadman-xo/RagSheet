<#
.SYNOPSIS
  Switch the chat LLM server between Ollama and vLLM with one command.

  .\scripts\llm.ps1                 # switch to the other server (toggle)
  .\scripts\llm.ps1 -Use vllm       # use vLLM   (Qwen/Qwen3-4B-AWQ, 8 slots)
  .\scripts\llm.ps1 -Use ollama     # use Ollama (qwen3:4b-instruct-2507, 4 slots)
  .\scripts\llm.ps1 -Use status     # show the current server, model, and state

  What it does:
  1. Stops the other LLM server (a 6 GB GPU holds only one model).
  2. Changes only the LLM lines in .env, so the choice stays after a restart.
     The LLM lines of the server that you leave are saved in .env.llm-<server> (not in git)
     and come back when you switch back. Thus your own model choice (for example qwen3:8b) stays.
  3. Runs "docker compose up -d": it starts the selected server and restarts the gateway and the api.
     PostgreSQL, the data, and the scope files stay as they are.
  4. Waits until the gateway says "ready" and shows the result.

  Dashboards work during the switch. The chat gives basic answers (correct tables, no AI text)
  until the new server is ready: Ollama about 10-20 s, vLLM about 1-2 minutes.
  The first switch to vLLM downloads its image (31 GB on disk) and the model (2.5 GB).
#>
param([ValidateSet("toggle", "ollama", "vllm", "status")][string]$Use = "toggle", [int]$TimeoutS = 600)
$ErrorActionPreference = 'Continue'  # PowerShell 5.1 treats docker progress on stderr as an error with 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

$KEYS = @('COMPOSE_PROFILES', 'LLM_PROVIDER', 'LLM_ENDPOINT', 'LLM_MODEL', 'LLM_PARALLEL', 'LLM_TURN_ESTIMATE_S')
$DEFAULTS = @{
    ollama = [ordered]@{ COMPOSE_PROFILES = 'bundled-llm'; LLM_PROVIDER = 'ollama'; LLM_ENDPOINT = 'http://ollama:11434';
                         LLM_MODEL = 'qwen3:4b-instruct-2507-q4_K_M'; LLM_PARALLEL = '4'; LLM_TURN_ESTIMATE_S = '8' }
    vllm   = [ordered]@{ COMPOSE_PROFILES = 'vllm'; LLM_PROVIDER = 'openai_compatible'; LLM_ENDPOINT = 'http://vllm:8000/v1';
                         LLM_MODEL = 'Qwen/Qwen3-4B-AWQ'; LLM_PARALLEL = '8'; LLM_TURN_ESTIMATE_S = '4' }
}
$utf8 = New-Object System.Text.UTF8Encoding($false)
$envPath = Join-Path $root '.env'

function Read-EnvLines([string]$path) {
    if (-not (Test-Path $path)) { return @() }
    return ([IO.File]::ReadAllText($path, $utf8) -replace "`r", '') -split "`n"
}

function Get-EnvValue([string[]]$lines, [string]$key) {
    foreach ($l in $lines) { if ($l -match "^\s*$key\s*=(.*)$") { return $Matches[1].Trim() } }
    return $null
}

function Get-Current([string[]]$lines) {
    $p = Get-EnvValue $lines 'LLM_PROVIDER'
    if ($p -eq 'ollama' -or -not $p) { return 'ollama' }
    return 'vllm'
}

function Save-Settings([string[]]$lines, [string]$server) {
    $out = foreach ($k in $KEYS) { "$k=$(Get-EnvValue $lines $k)" }
    [IO.File]::WriteAllText((Join-Path $root ".env.llm-$server"), (($out -join "`n") + "`n"), $utf8)
}

function Load-Settings([string]$server) {
    $values = [ordered]@{}
    foreach ($k in $KEYS) { $values[$k] = $DEFAULTS[$server][$k] }
    $saved = Read-EnvLines (Join-Path $root ".env.llm-$server")
    foreach ($k in $KEYS) { $v = Get-EnvValue $saved $k; if ($v) { $values[$k] = $v } }
    return $values
}

function Write-Env([string[]]$lines, $values) {
    $done = @{}
    $out = foreach ($l in $lines) {
        $hit = $null
        foreach ($k in $KEYS) { if ($l -match "^\s*$k\s*=") { $hit = $k } }
        if ($hit) { "$hit=$($values[$hit])"; $done[$hit] = $true } else { $l }
    }
    $extra = foreach ($k in $KEYS) { if (-not $done[$k]) { "$k=$($values[$k])" } }
    $text = ((@($out) + @($extra)) -join "`n").TrimEnd("`n") + "`n"
    [IO.File]::WriteAllText($envPath, $text, $utf8)
}

function Get-Status {
    # The api container asks the gateway (it has the gateway token). Base64 avoids quote problems in PowerShell 5.1.
    $py = @'
import asyncio, json
from app.chat import gateway_client as g
async def main():
    await g.startup()
    s = await g.status()
    e = (s.get("endpoints") or [{}])[0]
    print(json.dumps({"state": s.get("state"), "provider": e.get("provider"), "model": e.get("model"),
                      "slots": e.get("slots"), "model_state": e.get("model_state"), "error": e.get("model_error")}))
asyncio.run(main())
'@
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($py))
    $raw = docker compose exec -T api python -c "import base64;exec(base64.b64decode('$b64'))" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
    try { return ($raw | Select-Object -Last 1) | ConvertFrom-Json } catch { return $null }
}

function Show-Status($s) {
    if (-not $s) { Write-Host "  The api is not running or not ready yet." -ForegroundColor Yellow; return }
    $color = if ($s.state -eq 'ready') { 'Green' } else { 'Yellow' }
    Write-Host ("  state: {0}   provider: {1}   model: {2}   slots: {3}" -f $s.state, $s.provider, $s.model, $s.slots) -ForegroundColor $color
    if ($s.error) { Write-Host "  last error: $($s.error)" -ForegroundColor DarkYellow }
}

try {
    docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Docker is not running. Start Docker Desktop first." }

    $lines = Read-EnvLines $envPath
    $current = Get-Current $lines
    if ($Use -eq 'status') {
        Write-Host "LLM server in .env: $current"
        Show-Status (Get-Status)
        exit 0
    }
    $target = if ($Use -eq 'toggle') { if ($current -eq 'ollama') { 'vllm' } else { 'ollama' } } else { $Use }
    $other = if ($target -eq 'ollama') { 'vllm' } else { 'ollama' }
    Write-Host "Switch the chat LLM server: $current -> $target"

    if ($target -eq 'vllm') {
        docker image inspect vllm/vllm-openai:v0.10.1.1 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Host "  The vLLM image is not on this computer. Docker downloads it now (31 GB on disk)." -ForegroundColor Yellow }
    }

    # 1. Save the settings of the server that we leave, then stop it (both profiles, so compose can find it).
    if ($current -ne $target) { Save-Settings $lines $current }
    Write-Host "  stopping $other ..."
    $env:COMPOSE_PROFILES = 'bundled-llm,vllm'
    docker compose stop $other 2>&1 | Out-Null
    Remove-Item env:COMPOSE_PROFILES

    # 2. Change only the LLM lines in .env.
    $values = Load-Settings $target
    Write-Env $lines $values
    Write-Host ("  .env: LLM_PROVIDER={0}, LLM_MODEL={1}, LLM_PARALLEL={2}" -f $values.LLM_PROVIDER, $values.LLM_MODEL, $values.LLM_PARALLEL)

    # 3. Start the selected server; compose restarts the gateway and the api because their settings changed.
    Write-Host "  starting $target, the gateway, and the api ..."
    docker compose up -d 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed. Run 'docker compose up -d' to see the error." }

    # 4. Wait for the gateway.
    $t0 = Get-Date
    $s = $null
    while (((Get-Date) - $t0).TotalSeconds -lt $TimeoutS) {
        $s = Get-Status
        if ($s -and $s.state -eq 'ready' -and $s.provider -eq $values.LLM_PROVIDER) { break }
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 5
    }
    Write-Host ""
    Show-Status $s
    if ($s -and $s.state -eq 'ready') {
        Write-Host ("Done in {0:N0} s. The chat now uses {1}." -f ((Get-Date) - $t0).TotalSeconds, $target) -ForegroundColor Green
        if ($target -eq 'vllm') { Write-Host "Note: .env is in git. 'git status' shows it as changed while vLLM is selected." }
        exit 0
    }
    Write-Host "The server is not ready after $TimeoutS s. The chat gives basic answers until it is ready." -ForegroundColor Yellow
    Write-Host "See the log: docker compose logs $target --tail 50"
    exit 1
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
