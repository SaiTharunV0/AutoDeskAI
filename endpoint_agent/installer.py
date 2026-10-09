"""No subprocess, shell, command strings, or dynamic executable paths."""
SUPPORTED_SOFTWARE = frozenset({"vscode"})
def install(software: str, simulation: bool = True) -> dict:
    if software not in SUPPORTED_SOFTWARE:
        raise ValueError("Software not supported by this endpoint")
    if not simulation:
        raise ValueError("Real installation is not enabled in this prototype")
    return {"success": True, "simulated": True}
