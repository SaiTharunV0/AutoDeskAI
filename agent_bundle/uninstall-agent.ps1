$ErrorActionPreference = 'Stop'
$destination = Join-Path $env:LOCALAPPDATA 'AutoDeskAI\Agent'
$taskName = 'AutoDeskAI Endpoint Agent'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
foreach ($name in @('AutoDeskAI-Agent.exe','launch-agent.ps1','.env')) {
    $file = Join-Path $destination $name
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
}
if (Test-Path -LiteralPath $destination) {
    Remove-Item -LiteralPath $destination -ErrorAction SilentlyContinue
}
Write-Host 'Local AutoDeskAI agent removed. An administrator can disable the enrolled device in Manage workspace.'
