"""Opt-in live smoke test using only the configured dedicated test accounts."""
import argparse
import getpass
import secrets

import httpx

import config
from endpoint_agent import config as agent_config
from endpoint_agent.agent import run_once
from endpoint_agent.api import AgentAPI


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="create a real VS Code install task and provision Jira Developer")
    args = parser.parse_args()
    server_url = httpx.URL("http://127.0.0.1:8000")
    if args.execute and agent_config.SERVER_URL:
        server_url = httpx.URL(agent_config.SERVER_URL)
    with httpx.Client(base_url=str(server_url).rstrip("/"), timeout=180) as client:
        health = client.get("/")
        health.raise_for_status()
        if not args.execute:
            print("Backend is reachable. No account, request, installation, or Jira change was made.")
            print("After configuring the dedicated test account and endpoint agent, run with --execute.")
            return
        if not (config.ENTRA_TEST_ACCOUNT_UPN and
                config.ENTRA_TEST_ACCOUNT_UPN == config.JIRA_TEST_ACCOUNT_EMAIL):
            raise SystemExit("Entra and Jira test-account emails must match before running live workflows.")
        if not all((config.JIRA_BASE_URL, config.JIRA_EMAIL, config.JIRA_API_TOKEN,
                    config.JIRA_PROJECT_KEY, config.JIRA_TEST_ACCOUNT_ID)):
            raise SystemExit("Configure the Jira test project and dedicated test account before executing.")
        agent_config.validate()
        email = input("Dedicated test account email: ").strip().lower()
        if email != config.ENTRA_TEST_ACCOUNT_UPN:
            raise SystemExit("Only the configured dedicated test account is allowed.")
        password = getpass.getpass("AutoDeskAI test-account password: ")
        response = client.post("/auth/login", json={"email": email, "password": password})
        response.raise_for_status()
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        devices = client.get("/devices", headers=headers)
        devices.raise_for_status()
        device = next((item for item in devices.json()
                       if item["device_id"] == agent_config.DEVICE_ID
                       and item["status"] == "ACTIVE"), None)
        if not device or not agent_config.AGENT_TOKEN:
            raise SystemExit("The configured test account needs an active, enrolled agent device.")
        agent = AgentAPI(str(server_url).rstrip("/"), agent_config.AGENT_TOKEN)
        try:
            heartbeat = agent.heartbeat()
            if heartbeat["device_id"] != device["device_id"]:
                raise SystemExit("Agent credentials do not match the selected enrolled device.")
            install_response = client.post("/requests", headers=headers, json={
                "message": "Install VS Code",
                "device_id": device["id"],
                "idempotency_key": secrets.token_hex(16),
            })
            install_response.raise_for_status()
            install_request = install_response.json()
            if install_request["status"] != "PENDING":
                raise SystemExit("VS Code request was not queued: " + install_request["message"])
            run_once(agent, agent_config.DEVICE_ID, simulation=False)
            status = client.get(f'/requests/{install_request["id"]}', headers=headers)
            status.raise_for_status()
            if status.json()["status"] != "COMPLETED":
                raise SystemExit("Endpoint did not verify the VS Code installation.")
            print("VS Code install and endpoint verification completed.")

            jira_response = client.post("/requests", headers=headers, json={
                "message": "Give me developer access to Jira",
                "idempotency_key": secrets.token_hex(16),
            })
            jira_response.raise_for_status()
            jira_request = jira_response.json()
            if jira_request["status"] != "COMPLETED":
                raise SystemExit("Jira role was not provisioned and verified: " + jira_request["message"])
            print("Jira Developer role provisioned and verified.")
        finally:
            agent.close()
        print("Live test complete. Password reset and password change require their interactive Microsoft flows.")


if __name__ == "__main__":
    main()
