param(
    [string]$Time = "12:30",
    [string]$TaskName = "ArxivWeekdayUpdate"
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$runScript = Join-Path $repoRoot "scripts\run_daily.ps1"
$taskCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runScript`""

schtasks /Create /TN $TaskName /TR $taskCmd /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST $Time /F
