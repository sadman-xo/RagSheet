<#
.SYNOPSIS
  Checks the computer before "docker compose up": Docker, GPU, port, disk, memory, and the database connection rule.
#>
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$ok = $true

function Pass($m) { Write-Host "  [ok]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [fail] $m" -ForegroundColor Red; $script:ok = $false }

# Read .env
$envVars = @{}
Get-Content (Join-Path $root '.env') | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $envVars[$Matches[1]] = $Matches[2] }
}

Write-Host "Panorama environment check"

# 1. Docker
$dockerVersion = docker version --format '{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -eq 0 -and $dockerVersion) { Pass "Docker server $dockerVersion" } else { Fail "Docker is not running. Start Docker Desktop." }
$composeVersion = docker compose version --short 2>$null
if ($composeVersion) { Pass "Docker Compose $composeVersion" } else { Fail "Docker Compose v2 is missing." }

# 2. GPU
$gpu = $null
try { $gpu = nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader,nounits 2>$null } catch {}
if ($gpu) {
    $parts = $gpu.Split(',') | ForEach-Object { $_.Trim() }
    $free = [int]$parts[1] - [int]$parts[2]
    Pass "GPU $($parts[0]): $free MiB free of $($parts[1]) MiB"
    if ($free -lt 4500) {
        Warn "Less than 4.5 GB of VRAM is free. Close GPU apps, or set Edge and Teams to 'Power saving' in Windows graphics settings."
        Warn "A host Ollama with a loaded model also uses VRAM. Stop it, or wait until it unloads the model."
    }
} else {
    Warn "No NVIDIA GPU found. Use the CPU mode. Put these lines in .env:"
    Write-Host "         COMPOSE_FILE=docker-compose.yml"
    Write-Host "         LLM_MODEL=qwen3:4b"
    Write-Host "         OLLAMA_MEM_LIMIT=5g"
    Write-Host "         LLM_TURN_ESTIMATE_S=45"
    Write-Host "         LLM_MAX_WAIT_S=60"
}

# 3. Port 8080
$listen = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    $owner = (Get-Process -Id $listen[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
    if ($owner -match 'docker|wslrelay|com.docker') { Pass "Port 8080 is used by Docker (Panorama is running)" }
    else { Fail "Port 8080 is used by '$owner'. Stop that program." }
} else { Pass "Port 8080 is free" }

# 4. Disk
$drive = (Get-Item $root).PSDrive
$freeGb = [math]::Round($drive.Free / 1GB, 1)
if ($freeGb -ge 20) { Pass "Disk $($drive.Name): $freeGb GB free" } else { Warn "Disk $($drive.Name): only $freeGb GB free (model 5.2 GB + images ~6 GB + 1M dataset ~1 GB)" }

# 5. WSL2 memory
$wslconfig = Join-Path $env:USERPROFILE '.wslconfig'
$mem = $null
if (Test-Path $wslconfig) {
    $line = Select-String -Path $wslconfig -Pattern '^\s*memory\s*=\s*(\S+)' | Select-Object -First 1
    if ($line) { $mem = $line.Matches[0].Groups[1].Value }
}
if ($mem) { Pass "WSL2 memory = $mem (.wslconfig)" }
else { Warn "WSL2 uses its default memory (half of RAM). For load test L or 3 replicas with the model, set memory=12GB in $wslconfig." }

# 6. Database connection rule: replicas x workers x 10 + init <= 80
$replicas = [int]($envVars['API_REPLICAS'] | ForEach-Object { if ($_) { $_ } else { 2 } })
$workers = [int]($envVars['API_WORKERS'] | ForEach-Object { if ($_) { $_ } else { 1 } })
$conns = $replicas * $workers * 10 + 2
if ($conns -le 80) { Pass "Database connections: $replicas replicas x $workers workers x 10 + init = $conns (limit 80)" }
else { Fail "Database connections: $conns > 80. Lower API_REPLICAS or API_WORKERS." }

# 7. Dataset mode
Pass "DATASET=$($envVars['DATASET']), LLM_MODEL=$($envVars['LLM_MODEL']), LLM_PARALLEL=$($envVars['LLM_PARALLEL']), profiles=$($envVars['COMPOSE_PROFILES'])"

if ($ok) { Write-Host "Result: ready. Run: docker compose up -d --build" -ForegroundColor Green; exit 0 }
else { Write-Host "Result: fix the items marked [fail]." -ForegroundColor Red; exit 1 }
