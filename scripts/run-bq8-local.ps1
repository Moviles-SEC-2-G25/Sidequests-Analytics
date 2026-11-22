param(
    [switch]$Publish,
    [switch]$Dashboard,
    [string]$PythonExe = ''
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

# Optional explicit environment: permits a clean worktree/clone while preserving
# an older checkout with uncommitted changes and its already installed venv.
if ($PythonExe) {
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Python executable not found at the supplied -PythonExe path."
    }
    $python = $PythonExe
} else {
    $python = Join-Path (Split-Path -Parent $repo) 'analytics-venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $python = Join-Path $repo '.venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Python venv not found. Use -PythonExe with an existing venv or create .venv here."
    }
}

$argsForPython = @((Join-Path $PSScriptRoot 'run_bq8_local.py'))
if ($Publish) { $argsForPython += '--publish' }
if ($Dashboard) { $argsForPython += '--dashboard' }
& $python -B @argsForPython
exit $LASTEXITCODE
