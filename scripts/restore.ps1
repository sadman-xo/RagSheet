<#
.SYNOPSIS
  Restores a backup made by backup.ps1. It stops the api replicas and the gateway, runs pg_restore,
  runs init (the scope files are rebuilt from the database if necessary), and starts them again.
  Usage: .\scripts\restore.ps1 -File backups\panorama_20261007_120000.dump
#>
param([Parameter(Mandatory = $true)][string]$File)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if (-not (Test-Path $File)) { throw "File not found: $File" }
    $name = Split-Path $File -Leaf
    Write-Host "Stopping the api replicas and the gateway"
    docker compose stop api llm-gateway | Out-Null
    docker compose cp $File "postgres:/tmp/$name" | Out-Null
    Write-Host "Restoring $name"
    docker compose exec -T postgres pg_restore -U postgres -d panorama --clean --if-exists "/tmp/$name"
    if ($LASTEXITCODE -ne 0) { Write-Host "pg_restore reported warnings (exit $LASTEXITCODE); continuing" -ForegroundColor Yellow }
    docker compose exec -T postgres rm -f "/tmp/$name"
    Write-Host "Running init"
    docker compose run --rm init
    if ($LASTEXITCODE -ne 0) { throw "init failed" }
    Write-Host "Starting the api replicas and the gateway"
    docker compose up -d api llm-gateway | Out-Null
    Write-Host "Restore complete"
} finally { Pop-Location }
