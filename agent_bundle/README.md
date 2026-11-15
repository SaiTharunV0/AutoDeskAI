# AutoDeskAI Windows endpoint agent

This bundle contains only the endpoint agent and its installer. The target computer does **not** need Git, the project repository, or Python.

1. In AutoDeskAI, an administrator opens **Manage workspace → Add endpoint device**, chooses the employee owner, selects **Windows**, and records the exact device ID and one-time agent token.
2. On that employee's Windows computer, extract the entire `AutoDeskAI-Agent-Windows.zip` bundle. Windows Package Manager (`winget`) must be available to the signed-in user.
3. In PowerShell, change to the extracted folder and run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-agent.ps1`. Enter the **Render backend** URL, enrolled device ID, and one-time token when prompted. Do not use the Vercel frontend URL.
4. The installer checks the connection, copies the agent to the current user's local application folder, and creates a scheduled task that starts it when that user signs in. Check **Manage workspace** for **Connected**. The employee can then request approved software from **Software Installation**.

The token is stored in `%LOCALAPPDATA%\AutoDeskAI\Agent\.env` for the signed-in Windows user. Do not share the token or add the `.env` file to source control. To remove the local agent, run `uninstall-agent.ps1` from the extracted bundle and ask an administrator to disable the device record.

Download the bundle from the repository's **Actions → Windows endpoint agent bundle → latest successful run → Artifacts**. GitHub may require sign-in to download an Actions artifact. The executable is not code-signed, so Windows may show a publisher warning. This build creates a bundle for testing; verify the executable and installer on a designated Windows endpoint before wider deployment.
