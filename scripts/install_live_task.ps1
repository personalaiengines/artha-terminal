<#
ARTHA Terminal - register the LIVE F&O draw loop as a Windows Scheduled Task.

Fires DAILY, pre-IST-open, in your interactive logon session (CDP needs a real
desktop session — a GUI TradingView window). draw_live.py itself gates on IST:
it waits until 09:15 IST, redraws levels every interval, and exits after 15:30 IST
— so the single daily launch is correct regardless of this machine's timezone or
DST, and weekends/holidays cost one instant exit.

Run in an ELEVATED PowerShell (Register-ScheduledTask needs admin):
    powershell -ExecutionPolicy Bypass -File scripts\install_live_task.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install_live_task.ps1 -Uninstall

Optional: -Index nifty50   (default: all)   -MarginHours 2   (how early to launch)
#>
param(
    [string]$Index = "all",
    [double]$MarginHours = 2.0,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "ARTHA FnO Live Draw"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'."
    return
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$py = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "python not found at $py" }

# Launch time = IST 09:15 minus MarginHours, expressed in THIS machine's local time.
# Generous margin absorbs any DST drift of a fixed daily local trigger; the script
# just waits out the extra minutes pre-open.
$ist = [System.TimeZoneInfo]::FindSystemTimeZoneById("India Standard Time")
$nowIst = [System.TimeZoneInfo]::ConvertTime([DateTime]::UtcNow, [System.TimeZoneInfo]::Utc, $ist)
$openIst = (Get-Date -Date $nowIst.Date -Hour 9 -Minute 15 -Second 0).AddHours(-$MarginHours)
$openUtc = [System.TimeZoneInfo]::ConvertTimeToUtc($openIst, $ist)
$launchLocal = $openUtc.ToLocalTime()

$action = New-ScheduledTaskAction -Execute $py -Argument "scripts\draw_live.py $Index" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $launchLocal
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 10) -DontStopOnIdleEnd -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# Interactive: runs only when you're logged on, in your desktop session (required for CDP/GUI TV).
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Registered '$TaskName':"
Write-Host "  runs: $py scripts\draw_live.py $Index"
Write-Host "  daily at local $($launchLocal.ToString('HH:mm')) (= IST 09:15 minus ${MarginHours}h)"
Write-Host "  script waits to IST 09:15, redraws each interval, exits after IST 15:30."
Write-Host "Run once now to test:  Start-ScheduledTask -TaskName '$TaskName'"
