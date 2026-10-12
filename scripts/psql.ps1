<#
.SYNOPSIS
  Opens psql in the postgres container as the superuser (local socket, no password).
  Example: .\scripts\psql.ps1 -c "select count(*) from sales.fact_orders"
#>
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if ($args.Count -gt 0) { docker compose exec -T postgres psql -U postgres -d panorama @args }
    else { docker compose exec postgres psql -U postgres -d panorama }
} finally { Pop-Location }
