# ALgpt'yi her gun otomatik calistiran Windows Gorev Zamanlayici kaydi.
# Kullanim (PowerShell):  powershell -ExecutionPolicy Bypass -File install_task.ps1 [-Time 09:00]
# Kaldirmak icin:          Unregister-ScheduledTask -TaskName "ALgpt Daily Jobs" -Confirm:$false
param([string]$Time = "09:00")

$bat = Join-Path $PSScriptRoot "run_daily.bat"
$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
# Bilgisayar o saatte kapaliysa acilinca calisir; internet yoksa bekler; en fazla 3 saat.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# Chrome gorunur modda acildigi icin oturum acikken calisir (pencere ekran disinda durur).
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName "ALgpt Daily Jobs" -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Kaydedildi: 'ALgpt Daily Jobs' her gun $Time'da calisacak. Log: logs\run.log"
