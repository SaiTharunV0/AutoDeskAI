# Run as the Windows user who will receive the software installation.
$ErrorActionPreference = 'Stop'
$exe = Join-Path $PSScriptRoot 'AutoDeskAI-Agent.exe'
$launcher = Join-Path $PSScriptRoot 'launch-agent.ps1'
if (-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath $launcher)) {
    throw 'Extract the complete agent ZIP before running this installer.'
}
if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
    throw 'Windows Package Manager (winget) must be available for this user.'
}

$destination = Join-Path $env:LOCALAPPDATA 'AutoDeskAI\Agent'
if (Test-Path -LiteralPath (Join-Path $destination 'AutoDeskAI-Agent.exe')) {
    throw 'The agent is already installed. Run uninstall-agent.ps1 before reinstalling.'
}

$serverUrl = (Read-Host 'Backend URL (Render service, not the Vercel website)').Trim().TrimEnd('/')
$deviceId = (Read-Host 'Device ID exactly as enrolled in Manage workspace').Trim()
$secureToken = Read-Host 'One-time agent token from device enrollment' -AsSecureString
$tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer).Trim() }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer) }
$uri = $null
if (-not [Uri]::TryCreate($serverUrl, [UriKind]::Absolute, [ref]$uri) -or
    ($uri.Scheme -ne 'https' -and -not ($uri.Scheme -eq 'http' -and $uri.Host -in @('localhost','127.0.0.1'))) -or
    $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/') {
    throw 'Use the HTTPS backend origin without a path, query, or embedded credentials.'
}
if ($deviceId -notmatch '^[a-zA-Z0-9_.-]{3,100}$') { throw 'Device ID does not match the enrolled device format.' }
if ($token -notmatch '^[A-Za-z0-9_-]{32,}$') { throw 'The agent token format is invalid.' }

# Test the token and device against the backend before installing anything.
$env:SERVER_URL = $serverUrl
$env:DEVICE_ID = $deviceId
$env:AGENT_TOKEN = $token
$env:AGENT_INSTALL_MODE = 'real'
try {
    & $exe --check
    if ($LASTEXITCODE -ne 0) { throw 'Agent could not connect. Check the backend URL, device ID, and token.' }
} finally {
    Remove-Item Env:SERVER_URL,Env:DEVICE_ID,Env:AGENT_TOKEN,Env:AGENT_INSTALL_MODE -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Path $destination -Force | Out-Null
Copy-Item -LiteralPath $exe -Destination (Join-Path $destination 'AutoDeskAI-Agent.exe')
Copy-Item -LiteralPath $launcher -Destination (Join-Path $destination 'launch-agent.ps1')
$settings = @(
    "SERVER_URL=$serverUrl"
    "DEVICE_ID=$deviceId"
    "AGENT_TOKEN=$token"
    'AGENT_INSTALL_MODE=real'
    'AGENT_POLL_SECONDS=10'
)
Set-Content -LiteralPath (Join-Path $destination '.env') -Value $settings -Encoding ascii

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskName = 'AutoDeskAI Endpoint Agent'
$taskArguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $destination 'launch-agent.ps1') + '"'
$taskAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $taskArguments -WorkingDirectory $destination
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $taskTrigger -Principal $taskPrincipal -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host 'AutoDeskAI agent installed and started. Check Manage workspace for Connected status.'
