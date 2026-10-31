param([double]$ObservationHours = 24, [switch]$ReadOnly, [switch]$Dashboard)
$ErrorActionPreference = 'Stop'
$bq3Repo = Split-Path -Parent $PSScriptRoot
$bq3Venv = Join-Path (Split-Path -Parent $bq3Repo) 'analytics-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $bq3Venv)) {
    throw 'No se encontro el entorno analytics-venv. Instala requirements.txt en tu entorno Python.'
}
$bq3Args = @((Join-Path $PSScriptRoot 'run_bq3_local.py'), '--observation-hours', $ObservationHours.ToString([Globalization.CultureInfo]::InvariantCulture))
if ($ReadOnly) { $bq3Args += '--read-only' }
if ($Dashboard) { $bq3Args += '--dashboard' }
& $bq3Venv -B @bq3Args
exit $LASTEXITCODE
