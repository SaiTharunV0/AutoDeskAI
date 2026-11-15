$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& (Join-Path $PSScriptRoot 'AutoDeskAI-Agent.exe')
$agentExitCode = $LASTEXITCODE
if ($agentExitCode -eq 10) {
    # The backend accepted a verified installation result. Do not restart at next sign-in.
    if (Get-ScheduledTask -TaskName 'AutoDeskAI Endpoint Agent' -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName 'AutoDeskAI Endpoint Agent' -Confirm:$false
    }
    Write-Host 'Installation complete. Endpoint agent stopped.'
    exit 0
}
exit $agentExitCode
