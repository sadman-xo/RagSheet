<#
.SYNOPSIS
  Backs up the PostgreSQL database (pg_dump -Fc in the container) to .\backups\.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    New-Item -ItemType Directory -Force backups | Out-Null
    $ts = Get-Date -Format 'yyyyMMdd_HHmmss'
    $name = "panorama_$ts.dump"
    docker compose exec -T postgres pg_dump -U postgres -d panorama -Fc -f "/tmp/$name"
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
    docker compose cp "postgres:/tmp/$name" "backups/$name" | Out-Null
    docker compose exec -T postgres rm -f "/tmp/$name"
    $size = [math]::Round((Get-Item "backups/$name").Length / 1MB, 1)
    Write-Host "Backup written: backups\$name ($size MB)"
} finally { Pop-Location }
