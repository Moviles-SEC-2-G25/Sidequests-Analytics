param([switch]$Publish, [switch]$Dashboard)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path (Split-Path -Parent $repo) 'analytics-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $repo '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Python venv not found. Create analytics-venv next to this repo or .venv in the repo; install requirements.txt.'
}
$argsForPython = @((Join-Path $PSScriptRoot 'run_bq8_local.py'))
if ($Publish) { $argsForPython += '--publish' }
if ($Dashboard) { $argsForPython += '--dashboard' }
& $python -B @argsForPython
exit $LASTEXITCODE
