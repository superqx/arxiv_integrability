param(
    [switch]$InstallDeps,
    [int]$DaysBack,
    [string]$Date
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (!(Test-Path $pythonExe)) {
    $pythonExe = "python"
}

Set-Location $repoRoot

if ($InstallDeps) {
    & $pythonExe -m pip install -r requirements.txt
}

$env:PYTHONPATH = if (Test-Path (Join-Path $repoRoot ".deps")) { Join-Path $repoRoot ".deps" } else { $env:PYTHONPATH }

$argsList = @()
if ($DaysBack) { $argsList += @("--days_back", $DaysBack) }
if ($Date) { $argsList += @("--date", $Date) }

& $pythonExe daily_arxiv.py @argsList
