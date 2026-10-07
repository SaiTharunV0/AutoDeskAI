"""Executable capabilities are defined in code, never by model or API input."""
SOFTWARE = {
    "vscode": {"display_name": "Visual Studio Code", "aliases": ("vscode", "vs code", "visual studio code")},
    "chrome": {"display_name": "Google Chrome", "aliases": ("chrome", "google chrome")},
}
APPLICATIONS = {"jira": "Jira"}
ACCESS_ROLES = {
    "jira_user": {"display_name": "Jira User", "jira_role": "Users"},
    "developer": {"display_name": "Developer", "jira_role": "Developers"},
    "project_admin": {"display_name": "Project Admin", "jira_role": "Administrators"},
}


def software_key(value):
    normalized = (value or "").strip().lower()
    return next((key for key, item in SOFTWARE.items() if normalized in item["aliases"]), None)
