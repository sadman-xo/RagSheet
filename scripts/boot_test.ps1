<#
.SYNOPSIS
  Clean-start test (needs Docker). It removes the state volumes, starts the stack with 2 api replicas, and checks:
  one set of secrets, 13 demo users, one data load, one scope-file build, one RAG build, the same C- pseudonym
  from both replicas, and the smoke test. Then a second "up" must skip the load and the builds.

  By default the model, Hugging Face, and generated-dataset volumes stay (no new 2.5 GB download).
  -Full removes them too (the same as "docker compose down -v").

  Usage: .\scripts\boot_test.ps1 [-Dataset sample|1m] [-Full]
#>
param([ValidateSet("sample", "1m")][string]$Dataset = "sample", [switch]$Full)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
$fail = 0
$base = "http://localhost:8080"

function Check($ok, $msg) {
    if ($ok) { Write-Host "  [ok]   $msg" -ForegroundColor Green } else { Write-Host "  [fail] $msg" -ForegroundColor Red; $script:fail++ }
}

function WaitHealthy([int]$replicas) {
    for ($i = 0; $i -lt 300; $i++) {
        $healthy = (docker compose ps api --format '{{.Health}}' | Where-Object { $_ -eq 'healthy' }).Count
        $front = docker compose ps frontend --format '{{.Health}}'
        if ($healthy -ge $replicas -and $front -eq 'healthy') { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Psql([string]$sql) {
    return (docker compose exec -T postgres psql -U postgres -d panorama -At -c $sql | Out-String).Trim()
}

function Login([string]$user) {
    $body = @{ username = $user; password = "Demo@2024"; want_token = $true } | ConvertTo-Json -Compress
    $r = Invoke-RestMethod -Method Post -Uri "$base/api/auth/login" -Body $body -ContentType 'application/json' -Headers @{ Origin = $base }
    return $r.access_token
}

$env:API_REPLICAS = "2"
$env:DATASET = $Dataset

Write-Host "1. Remove the state volumes"
docker compose down --remove-orphans 2>&1 | Out-Null
$volumes = 'secrets_db', 'secrets_app', 'secrets_gw', 'pg_data', 'scopes'
if ($Full) { $volumes += 'datasets', 'ollama_models', 'hf_cache' }
foreach ($v in $volumes) { docker volume rm -f "panorama_$v" 2>&1 | Out-Null }
Write-Host "   removed: $($volumes -join ', ')"

Write-Host "2. First start (DATASET=$Dataset, API_REPLICAS=2)"
$t0 = Get-Date
docker compose up -d --build 2>&1 | Out-Null
Check (WaitHealthy 2) "all services healthy in $([int]((Get-Date) - $t0).TotalSeconds) s"
$secretsLog = docker compose logs secrets --no-log-prefix | Out-String
$initLog = docker compose logs init --no-log-prefix | Out-String
Check ($secretsLog -match 'created' -and $secretsLog -notmatch 'created nothing') "secrets were created"
Check ([regex]::Matches($initLog, 'loader: loaded \d+ rows').Count -eq 1) "one data load"
Check ([regex]::Matches($initLog, 'scopestore: built 12 scope files').Count -eq 1) "one scope-file build (12 files)"
Check ([regex]::Matches($initLog, 'rag: built \d+ documents').Count -eq 1) "one RAG build"
Check ($initLog -match 'seeded 13 demo users') "13 demo users seeded"
Check ((Psql "select count(*) from app.users where username not like 'lt.%'") -eq '13') "13 users in the database"
$secretHash1 = docker compose run --rm --no-deps --entrypoint sh secrets -c "cat /secrets/db/* /secrets/app/* /secrets/gw/* 2>/dev/null | sha256sum" 2>$null | Select-Object -Last 1

Write-Host "3. The same customer pseudonym from both replicas"
$token = Login "analyst"
$h = @{ Authorization = "Bearer $token"; Origin = $base }
$first = Invoke-RestMethod -Method Post -Uri "$base/api/orders/search" -Headers $h -ContentType 'application/json' -Body '{"limit": 1, "with_total": false}'
$orderId = $first.rows[0].order_id
$seen = @{}
for ($i = 0; $i -lt 20 -and $seen.Count -lt 2; $i++) {
    $r = Invoke-WebRequest -Uri "$base/api/orders/$orderId" -Headers $h -UseBasicParsing
    $replica = $r.Headers['X-Replica']
    $cid = ($r.Content | ConvertFrom-Json).order.customer_id
    if (-not $cid) { $cid = ($r.Content | ConvertFrom-Json).customer_id }
    $seen[$replica] = $cid
}
$ids = @($seen.Values | Select-Object -Unique)
Check ($seen.Count -ge 2) "answers came from $($seen.Count) replicas"
Check ($ids.Count -eq 1 -and "$($ids[0])" -like 'C-*') "same pseudonym on all replicas ($($ids -join ', '))"

Write-Host "4. Smoke test through the load balancer"
& "$PSScriptRoot\smoke.ps1" -BaseUrl $base | Out-Host
Check ($LASTEXITCODE -eq 0) "smoke test"

Write-Host "5. Second start: nothing is loaded or built again"
docker compose up -d 2>&1 | Out-Null
Check (WaitHealthy 2) "all services healthy"
$initLog2 = docker compose logs init --no-log-prefix --since 5m | Out-String
Check ($initLog2 -match 'is already loaded; skip') "data load skipped"
Check ($initLog2 -match 'manifest for \w+ is current; skip') "scope-file build skipped"
Check ($initLog2 -match 'corpus_hash is the same; skip') "RAG build skipped"
Check ($initLog2 -match 'seeded 0 demo users') "no new users"
$secretHash2 = docker compose run --rm --no-deps --entrypoint sh secrets -c "cat /secrets/db/* /secrets/app/* /secrets/gw/* 2>/dev/null | sha256sum" 2>$null | Select-Object -Last 1
Check ($secretHash1 -and $secretHash1 -eq $secretHash2) "secrets did not change"

Remove-Item env:API_REPLICAS, env:DATASET -ErrorAction SilentlyContinue
Pop-Location
if ($fail -gt 0) { Write-Host "boot test: $fail check(s) failed" -ForegroundColor Red; exit 1 }
Write-Host "boot test: all checks passed" -ForegroundColor Green
exit 0
