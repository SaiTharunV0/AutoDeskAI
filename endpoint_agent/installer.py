"""Install only fixed, administrator-approved packages on a Windows endpoint."""
import platform
import re
import shutil
import subprocess

PACKAGES = {"vscode": "Microsoft.VisualStudioCode"}
INSTALL_TIMEOUT_SECONDS = 1200
VERIFY_TIMEOUT_SECONDS = 45


def install(software: str, *, runner=subprocess.run, executable=None, system=None) -> dict:
    if software not in PACKAGES:
        raise ValueError("Software not supported by this endpoint")
    if (system or platform.system()) != "Windows":
        return {"success": False, "verified": False, "error_code": "UNSUPPORTED_OS"}
    winget = executable or shutil.which("winget.exe")
    if not winget:
        return {"success": False, "verified": False, "error_code": "WINGET_UNAVAILABLE"}
    package_id = PACKAGES[software]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        installed = runner(
            [winget, "install", "--id", package_id, "--exact", "--source", "winget",
             "--scope", "user", "--silent", "--no-upgrade", "--disable-interactivity",
             "--accept-package-agreements", "--accept-source-agreements"],
            shell=False, capture_output=True, text=True, errors='replace', timeout=INSTALL_TIMEOUT_SECONDS,
            creationflags=flags,
        )
        verified = runner(
            [winget, "list", "--id", package_id, "--exact", "--source", "winget",
             "--disable-interactivity", "--accept-source-agreements"],
            shell=False, capture_output=True, text=True, errors='replace', timeout=VERIFY_TIMEOUT_SECONDS,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "verified": False, "error_code": "TIMED_OUT"}
    except OSError:
        return {"success": False, "verified": False, "error_code": "INSTALL_FAILED"}
    # WinGet can return zero even when the list is empty. Require an exact ID cell.
    found = verified.returncode == 0 and any(
        re.search(r"(?<!\S)" + re.escape(package_id) + r"(?!\S)", line)
        for line in verified.stdout.splitlines()
    )
    if found:
        return {"success": True, "verified": True, "error_code": None}
    return {"success": False, "verified": False,
            "error_code": "INSTALL_FAILED" if installed.returncode != 0 else "VERIFICATION_FAILED"}
