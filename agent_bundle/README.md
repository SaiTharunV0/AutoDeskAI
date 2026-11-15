# AutoDeskAI Windows endpoint agent

This bundle contains only the endpoint agent and its installer. The target computer does **not** need Git, the project repository, or Python.

1. In AutoDeskAI, an administrator opens **Manage workspace → Add endpoint device**, chooses the employee owner, selects **Windows**, and records the exact device ID and one-time agent token.
2. On that employee's Windows computer, extract the entire `AutoDeskAI-Agent-Windows.zip` bundle. Windows Package Manager (`winget`) must be available to the signed-in user.
3. In PowerShell, change to the extracted folder and run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-agent.ps1`. Enter the **Render backend** URL, enrolled device ID, and one-time token when prompted. Do not use the Vercel frontend URL.
4. The installer checks the connection, copies the agent to the current user's local application folder, and creates a scheduled task that starts it when that user signs in. Check **Manage workspace** for **Connected**. The employee can then request approved software from **Software Installation**.

The token is stored in `%LOCALAPPDATA%\AutoDeskAI\Agent\.env` for the signed-in Windows user. Do not share the token or add the `.env` file to source control. After the backend accepts a verified software installation result, the agent exits and removes its sign-in scheduled task. The device will show offline after its heartbeat expires. To prepare for another installation, run `%LOCALAPPDATA%\AutoDeskAI\Agent\launch-agent.ps1` as the same Windows user and wait for **Connected** in Manage workspace before requesting software. To remove the local agent and token, run `uninstall-agent.ps1` from the extracted bundle and ask an administrator to disable the device record.

Download the public [AutoDeskAI-Agent-Windows.zip](https://github.com/SaiTharunV0/AutoDeskAI/releases/download/agent-v1.0.0/AutoDeskAI-Agent-Windows.zip) release asset. The executable is not code-signed, so Windows may show a publisher warning. Verify the executable and installer on a designated Windows endpoint before wider deployment.

Existing installations need an updated bundle to gain the automatic stop behavior. Stop the scheduled task, replace `AutoDeskAI-Agent.exe` and `launch-agent.ps1` in `%LOCALAPPDATA%\AutoDeskAI\Agent` with the files from the newly built bundle, then start the task again. Keep the existing `.env` and token in that folder. The older public release asset does not update itself.
