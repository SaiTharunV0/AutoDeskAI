"""Install fixed catalog entries through Windows Package Manager."""
import os
import subprocess
from pathlib import Path

from app.catalog import SOFTWARE


class InstallationError(RuntimeError):
    pass


PACKAGES = {
    "vscode": ("Microsoft.VisualStudioCode", "user"),
    "chrome": ("Google.Chrome", "machine"),
}
SUPPORTED_SOFTWARE = frozenset(PACKAGES)


def _installed_paths(software: str) -> tuple[Path, ...]:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    if software == "vscode":
        paths = [Path(program_files), Path(program_files_x86)]
        if local_app_data:
            paths.append(Path(local_app_data) / "Programs")
        return tuple(root / "Microsoft VS Code" / "Code.exe" for root in paths)
    if software == "chrome":
        paths = [Path(program_files), Path(program_files_x86)]
        if local_app_data:
            paths.append(Path(local_app_data))
        return tuple(root / "Google" / "Chrome" / "Application" / "chrome.exe" for root in paths)
    raise ValueError("Software not supported by this endpoint")


def _winget_executable() -> Path | None:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = [windows / "System32" / "winget.exe"]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Microsoft" / "WindowsApps" / "winget.exe")
    package_directory = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsApps"
    if package_directory.is_dir():
        candidates.extend(package / "winget.exe" for package in package_directory.glob(
            "Microsoft.DesktopAppInstaller_*"))
    return next((path for path in candidates if path.is_file()), None)


def install(software: str, simulation: bool = False) -> dict:
    if software not in SUPPORTED_SOFTWARE:
        raise ValueError("Software not supported by this endpoint")
    if not simulation:
        if os.name != "nt":
            raise InstallationError("Real software installation is supported on Windows endpoints only.")
        if any(path.is_file() for path in _installed_paths(software)):
            return {"success": True, "simulated": False}
        winget = _winget_executable()
        if not winget:
            raise InstallationError("Windows Package Manager is not installed on this endpoint.")
        package_id, scope = PACKAGES[software]
        try:
            result = subprocess.run(
                [
                    str(winget), "install", "--exact", "--id", package_id,
                    "--source", "winget", "--scope", scope, "--silent",
                    "--accept-package-agreements", "--accept-source-agreements",
                    "--disable-interactivity",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=900,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise InstallationError("Windows Package Manager could not complete the installation.") from None
        if result.returncode != 0:
            raise InstallationError("Windows Package Manager reported an installation failure.")
        if not any(path.is_file() for path in _installed_paths(software)):
            raise InstallationError("Installation finished but the application could not be verified.")
        return {"success": True, "simulated": False}
    return {"success": True, "simulated": True}
