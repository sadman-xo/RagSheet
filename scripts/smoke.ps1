<#
.SYNOPSIS
  Smoke test through the nginx load balancer: each demo user signs in and runs scoped queries.
  Usage: .\scripts\smoke.ps1 [-BaseUrl http://localhost:8080]
#>
param([string]$BaseUrl = "http://localhost:8080", [string]$Password = "Demo@2024")
$ErrorActionPreference = 'Stop'
$origin = $BaseUrl
$fail = 0

function Call($method, $path, $token, $body) {
    $h = @{ Origin = $origin }
    if ($token) { $h.Authorization = "Bearer $token" }
    $args = @{ Method = $method; Uri = "$BaseUrl$path"; Headers = $h; ContentType = 'application/json'; UseBasicParsing = $true }
    if ($body) { $args.Body = ($body | ConvertTo-Json -Depth 10 -Compress) }
    try {
        $r = Invoke-WebRequest @args
        return @{ status = [int]$r.StatusCode; json = ($r.Content | ConvertFrom-Json); replica = $r.Headers['X-Replica'] }
    } catch {
        $code = [int]$_.Exception.Response.StatusCode
        return @{ status = $code; json = $null; replica = $null }
    }
}

function Check($ok, $msg) {
    if ($ok) { Write-Host "  [ok]   $msg" -ForegroundColor Green } else { Write-Host "  [fail] $msg" -ForegroundColor Red; $script:fail++ }
}

Write-Host "Smoke test against $BaseUrl"
$live = Call GET "/api/health/ready" $null $null
Check ($live.status -eq 200) "ready (replica $($live.replica))"

$users = 'admin','exec','rm.asia','rm.europe','cm.electronics','analyst','ops'
$replicas = @{}
foreach ($u in $users) {
    $login = Call POST "/api/auth/login" $null @{ username = $u; password = $Password; want_token = $true }
    if ($login.status -ne 200) { Check $false "$u login ($($login.status))"; continue }
    $t = $login.json.access_token
    $scope = $login.json.scope.label
    $k = Call POST "/api/analytics/kpis" $t @{ filters = @{} ; compare = 'none' }
    $rev = ($k.json.kpis | Where-Object id -eq 'gross_revenue').value
    $hasMargin = [bool]($k.json.kpis | Where-Object id -eq 'margin_pct')
    Check ($k.status -eq 200) ("{0,-15} {1,-26} gross revenue {2,15:N2}  margin KPI: {3}" -f $u, $scope, $rev, $hasMargin)
    $q = Call POST "/api/analytics/query" $t @{ metrics = @('gross_revenue'); group_by = @('region') }
    $regions = ($q.json.rows | ForEach-Object { $_.region }) -join ', '
    Write-Host ("         regions: {0}" -f $regions)
    for ($i = 0; $i -lt 4; $i++) { $r = Call GET "/api/auth/me" $t $null; if ($r.replica) { $replicas[$r.replica] = 1 + [int]$replicas[$r.replica] } }
}

# Scope checks
$asia = (Call POST "/api/auth/login" $null @{ username = 'rm.asia'; password = $Password; want_token = $true }).json.access_token
$x = Call POST "/api/analytics/query" $asia @{ metrics = @('gross_revenue'); filters = @{ regions = @('Europe') } }
Check ($x.status -eq 403) "rm.asia asks for Europe -> 403"
$exec = (Call POST "/api/auth/login" $null @{ username = 'exec'; password = $Password; want_token = $true }).json.access_token
$dataset = (Call GET "/api/auth/me" $exec $null).json.data.dataset
$x = Call POST "/api/analytics/query" $asia @{ metrics = @('gross_revenue'); filters = @{ categories = @('Electronics'); years = @(2023); quarters = @(3) } }
$y = Call POST "/api/analytics/query" $exec @{ metrics = @('gross_revenue'); filters = @{ regions = @('Asia'); categories = @('Electronics'); years = @(2023); quarters = @(3) } }
Check ($x.json.totals.gross_revenue -eq $y.json.totals.gross_revenue) "rm.asia Electronics Q3 2023 = exec with Asia filter ($('{0:N2}' -f $x.json.totals.gross_revenue))"
$ops = (Call POST "/api/auth/login" $null @{ username = 'ops'; password = $Password; want_token = $true }).json.access_token
$x = Call POST "/api/analytics/query" $ops @{ metrics = @('margin_pct') }
Check ($x.status -eq 403) "ops asks for margin -> 403"
if ($dataset -eq 'sample') {
    Check ([math]::Round($y.json.totals.gross_revenue, 2) -eq 108012.34) "Asia Electronics Q3 2023 = 108,012.34 (sample data)"
    $x = Call POST "/api/analytics/query" $exec @{ metrics = @('gross_revenue', 'net_revenue', 'margin_pct') }
    Check ([math]::Round($x.json.totals.gross_revenue, 2) -eq 5284387.70) "exec gross revenue = 5,284,387.70 (sample data)"
} else {
    Write-Host "  [info] dataset '$dataset': the sample reference values are not checked"
}
$na = Call POST "/api/orders/search" $exec @{ limit = 1; filters = @{ regions = @('North America') }; with_total = $false }
$naOrder = $na.json.rows[0].order_id
$eu = (Call POST "/api/auth/login" $null @{ username = 'rm.europe'; password = $Password; want_token = $true }).json.access_token
$x = Call GET "/api/orders/$naOrder" $eu $null
Check ($naOrder -and $x.status -eq 404) "rm.europe opens $naOrder (a North America order) -> 404"

Write-Host "Replicas that answered: $(($replicas.Keys | ForEach-Object { "$_ ($($replicas[$_]))" }) -join ', ')"
Check ($replicas.Count -ge 2) "requests reached more than one api replica"
if ($fail -gt 0) { Write-Host "$fail check(s) failed" -ForegroundColor Red; exit 1 } else { Write-Host "All checks passed" -ForegroundColor Green }
