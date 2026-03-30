param(
    [switch]$InstallDeps,
    [int]$DaysBack,
    [string]$Date,
    [switch]$Reorganize
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$pythonExe = $null

if (Test-Path $venvPython) {
    try {
        & $venvPython --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $pythonExe = $venvPython
        }
    }
    catch {
        $pythonExe = $null
    }
}

if (-not $pythonExe) {
    if (Test-Path "C:\Python313\python.exe") {
        $pythonExe = "C:\Python313\python.exe"
    }
    else {
        throw "Python executable not found. Create a healthy .venv or install Python at C:\Python313\python.exe"
    }
}

Set-Location $repoRoot

if ($InstallDeps) {
    & $pythonExe -m pip install --target .deps -r requirements.txt
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$depsPath = Join-Path $repoRoot ".deps"
if (Test-Path $depsPath) {
    if ($env:PYTHONPATH) {
        $env:PYTHONPATH = "$depsPath;$env:PYTHONPATH"
    }
    else {
        $env:PYTHONPATH = $depsPath
    }
}

$argsList = @()
if ($DaysBack) { $argsList += @("--days_back", $DaysBack) }
if ($Date) { $argsList += @("--date", $Date) }
if ($Reorganize) { $argsList += "--update_paper_links" }

& $pythonExe daily_arxiv.py @argsList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
