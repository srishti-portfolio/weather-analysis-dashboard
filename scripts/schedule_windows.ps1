 # Registers a Windows Task Scheduler job that runs the pipeline every day at 07:00.
# Run once from the project folder:  powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1
# Remove it later with:              Unregister-ScheduledTask -TaskName "WeatherPipeline"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$Python = (Get-Command python).Source

$Action  = New-ScheduledTaskAction -Execute $Python -Argument "run_pipeline.py" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Daily -At 7:00am
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable

Register-ScheduledTask -TaskName "WeatherPipeline" -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Daily Open-Meteo ETL + SQL report refresh" -Force
Write-Host "Scheduled 'WeatherPipeline' daily at 07:00 (runs late if the PC was off)."
