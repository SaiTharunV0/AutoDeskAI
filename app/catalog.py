"""Executable capabilities are defined in code, never by model or API input."""
SOFTWARE = {
    "vscode": {"display_name": "Visual Studio Code", "aliases": ("vscode", "vs code", "visual studio code")},
}
APPLICATIONS = {"tableau": "Tableau"}
EXAMPLE_APPLICATIONS = {
    "github": "GitHub",
    "jira": "Jira",
    "powerbi": "Power BI",
}
def software_key(value):
    normalized = (value or "").strip().lower()
    return next((key for key, item in SOFTWARE.items() if normalized in item["aliases"]), None)
