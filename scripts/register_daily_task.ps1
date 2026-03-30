param(
    [string]$WeekdayTime = "12:30",
    [string]$WeekendTime = "13:00",
    [string]$WeekdayTaskName = "ArxivWeekdayUpdate",
    [string]$WeekendTaskName = "ArxivWeekendReorganize",
    [switch]$WeekdayOnly
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$runScript = Join-Path $repoRoot "scripts\run_daily.ps1"

$weekdayTaskCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runScript`""
schtasks /Create /TN $WeekdayTaskName /TR $weekdayTaskCmd /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST $WeekdayTime /F
Write-Host "Created/updated weekday task '$WeekdayTaskName' at $WeekdayTime (Mon-Fri)."

if (-not $WeekdayOnly) {
    $weekendTaskCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runScript`" -Reorganize"
    schtasks /Create /TN $WeekendTaskName /TR $weekendTaskCmd /SC WEEKLY /D SUN /ST $WeekendTime /F
    Write-Host "Created/updated weekend task '$WeekendTaskName' at $WeekendTime (Sunday)."
}
