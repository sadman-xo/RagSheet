<#
.SYNOPSIS
  Load tests with Locust (profile "loadtest"). Reports go to loadtest\reports\.

  R  replica scaling: DATASET=1m, Ollama stopped, dashboards only; 1, 2, 3 api replicas; user steps;
     during the 3-replica run one replica stops for 30 s.
  C  mixed load on the sample data: 200 users (70 % dashboards, 30 % chat), 1 min ramp, 5 min steady.
  L  mixed load on 1M rows: 500 users (80 % dashboards, 20 % chat), 2 min ramp, 5 min steady.
     Needs memory=12GB in %UserProfile%\.wslconfig (your change; the script does not change it).
  B  chat capacity: 1, 2, 4, 8, 16 concurrent chat users (chat only, short waits).

  Usage: .\scripts\loadtest.ps1 -Scenario C   (add -Quick for a short smoke run; -Replicas 3 for C, L, and B)
#>
param([ValidateSet("R", "C", "L", "B")][string]$Scenario = "C", [switch]$Quick, [int]$Replicas = 2)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$reports = Join-Path $root "loadtest\reports"
New-Item -ItemType Directory -Force $reports | Out-Null

function Up([int]$replicas, [string]$dataset, [int]$ltUsers) {
    $env:API_REPLICAS = "$replicas"; $env:DATASET = $dataset; $env:LOADTEST_USERS = "$ltUsers"
    docker compose up -d --scale api=$replicas frontend llm-gateway 2>&1 | Out-Null
    for ($i = 0; $i -lt 90; $i++) {
        $healthy = (docker compose ps api --format '{{.Health}}' | Where-Object { $_ -eq 'healthy' }).Count
        if ($healthy -ge $replicas) { break }
        Start-Sleep -Seconds 2
    }
    Start-Sleep -Seconds 3
    Write-Host "stack up: $replicas replica(s), DATASET=$dataset, LOADTEST_USERS=$ltUsers"
}

function Locust([string]$name, [int]$users, [int]$spawn, [string]$runTime, [double]$chatShare, [string]$dashWait, [string]$chatWait, [int]$ltUsers, [int]$processes = 2) {
    $prefix = "/mnt/locust/reports/${Scenario}_${ts}_$name"
    docker compose --profile loadtest run --rm `
        -e "LT_USERS=$ltUsers" -e "LT_WORKERS=$processes" -e "LT_CHAT_SHARE=$chatShare" -e "LT_DASH_WAIT=$dashWait" -e "LT_CHAT_WAIT=$chatWait" `
        -e "LT_SUMMARY=${prefix}_summary.json" `
        locust -f /mnt/locust/locustfile.py --host http://frontend --headless --users $users --spawn-rate $spawn `
        --run-time $runTime --processes $processes --csv $prefix --html "${prefix}.html" --only-summary 2>&1 |
        Select-String -Pattern 'Aggregated|scope_violation|chat:|LOADTEST SUMMARY|Name  ' | ForEach-Object { Write-Host "  $_" }
    return "${Scenario}_${ts}_$name"
}

function Snapshot([string]$name) {
    $out = Join-Path $reports "${Scenario}_${ts}_${name}_system.txt"
    "== docker stats" | Out-File $out -Encoding utf8
    docker stats --no-stream --format "{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}" | Out-File $out -Append -Encoding utf8
    "== pg_stat_database / connections" | Out-File $out -Append -Encoding utf8
    docker compose exec -T postgres psql -U postgres -d panorama -At -c "select 'xact_commit='||xact_commit||' backends='||numbackends from pg_stat_database where datname='panorama'" | Out-File $out -Append -Encoding utf8
    docker compose exec -T postgres psql -U postgres -d panorama -At -c "select replica, round(max(write_p95_ms)::numeric,1) as write_p95_ms, sum(audit_dropped) as dropped, sum(cache_hits) hits, sum(cache_misses) misses, sum(requests) requests from app.worker_stats where updated_at > now() - interval '3 minutes' group by replica" | Out-File $out -Append -Encoding utf8
    "== slowest statements" | Out-File $out -Append -Encoding utf8
    docker compose exec -T postgres psql -U postgres -d panorama -At -c "select round(mean_exec_time::numeric,2)||' ms  '||calls||'  '||left(regexp_replace(query,'\s+',' ','g'),100) from pg_stat_statements order by mean_exec_time desc limit 8" | Out-File $out -Append -Encoding utf8
    "== nvidia-smi" | Out-File $out -Append -Encoding utf8
    nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv 2>$null | Out-File $out -Append -Encoding utf8
    Write-Host "  system snapshot: $out"
}

$ramp = if ($Quick) { "30s" } else { "" }
switch ($Scenario) {
    "R" {
        docker compose stop ollama 2>&1 | Out-Null
        $steps = if ($Quick) { @(60) } else { @(40, 80, 160) }
        foreach ($n in 1, 2, 3) {
            Up $n "1m" 130
            foreach ($u in $steps) {
                $time = if ($Quick) { "40s" } else { "75s" }
                if ($n -eq 3 -and $u -eq $steps[-1]) {
                    # stop one replica for 30 s during the run
                    $job = Start-Job -ScriptBlock { param($r) Set-Location $r; Start-Sleep 25; $c = (docker compose ps api -q | Select-Object -First 1); docker stop $c | Out-Null; Start-Sleep 30; docker start $c | Out-Null } -ArgumentList $root
                    Locust "rep${n}_u${u}_stop" $u 40 $time 0 "0.05,0.2" "5,15" 130 | Out-Null
                    Receive-Job $job -Wait | Out-Null
                } else {
                    Locust "rep${n}_u${u}" $u 40 $time 0 "0.05,0.2" "5,15" 130 | Out-Null
                }
            }
            Snapshot "rep$n"
        }
        docker compose start ollama 2>&1 | Out-Null
    }
    "C" {
        Up $Replicas "sample" 200
        $time = if ($Quick) { "90s" } else { "6m" }
        Locust "mixed200" 200 4 $time 0.3 "2,6" "5,15" 200 | Out-Null
        Snapshot "mixed200"
    }
    "L" {
        Up $Replicas "1m" 500
        $time = if ($Quick) { "120s" } else { "7m" }
        Locust "mixed500_rep$Replicas" 500 5 $time 0.2 "2,6" "5,15" 500 | Out-Null
        Snapshot "mixed500_rep$Replicas"
    }
    "B" {
        Up $Replicas "sample" 130
        foreach ($u in 1, 2, 4, 8, 16) {
            Locust "chat$u" $u $u "90s" 1.0 "1,2" "0.5,1" 130 1 | Out-Null
        }
        Snapshot "chat"
    }
}
Remove-Item env:API_REPLICAS, env:DATASET, env:LOADTEST_USERS -ErrorAction SilentlyContinue
Write-Host "Reports: $reports (prefix ${Scenario}_${ts}_)"
Pop-Location
