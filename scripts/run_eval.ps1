<#
.SYNOPSIS
  Runs the gold evaluation set against the running stack (through nginx) and writes a report to
  backend\eval\reports\ (the Admin AI quality page shows latest.json).
  Usage:
    .\scripts\run_eval.ps1                      # full eval with the configured model
    .\scripts\run_eval.ps1 -Label qwen3-4b      # name the report
    .\scripts\run_eval.ps1 -NumericOnly -Csv /datasets/generated_1000000.csv -Label 1m
#>
param([string]$Label = "qwen3-8b", [switch]$NumericOnly, [string]$Csv = "", [string]$Only = "")
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $args = @("python", "-m", "eval.run_eval", "--base", "http://frontend", "--label", $Label, "--out", "/app/eval/reports")
    if ($NumericOnly) { $args += "--numeric-only" }
    if ($Csv) { $args += @("--csv", $Csv) }
    if ($Only) { $args += @("--only", $Only) }
    docker compose --profile test run --rm --no-deps `
        -v "${root}/backend/eval/reports:/app/eval/reports" `
        -v "panorama_datasets:/datasets:ro" `
        tests @args
    exit $LASTEXITCODE
} finally { Pop-Location }
