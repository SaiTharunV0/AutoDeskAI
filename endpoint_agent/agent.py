"""Run with python -m endpoint_agent.agent. Enrollment is administrator-controlled."""
import argparse
import time
import httpx
from endpoint_agent import config
from endpoint_agent.api import AgentAPI
from endpoint_agent.installer import install

def run_once(api, device_id, pending=None):
    pending = pending if pending is not None else {}
    completed_install = False
    device = api.heartbeat()
    if device["device_id"] != device_id:
        raise ValueError("Configured device does not match authenticated device")
    # Retry results before claiming more work. Backend result handling is idempotent.
    for task_id, result in list(pending.items()):
        try:
            api.report(task_id, result)
            completed_install |= result.get("success") is True and result.get("verified") is True
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in (404, 409):
                raise
            # A timed-out/deleted/finalized task must not block all future work.
        del pending[task_id]
    for task in api.tasks():
        if task["device_id"] != device["id"] or task["status"] != "PROCESSING":
            raise ValueError("Task does not belong to this registered device")
        try:
            result = install(task["software"])
        except ValueError:
            result = {"success": False, "verified": False, "error_code": "INSTALL_FAILED"}
        pending[task["id"]] = result
        api.report(task["id"], result)
        completed_install |= result.get("success") is True and result.get("verified") is True
        del pending[task["id"]]
    return completed_install

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true", help="Verify enrollment without claiming installation tasks")
    args = parser.parse_args()
    config.validate()
    api = AgentAPI(config.SERVER_URL, config.AGENT_TOKEN)
    if args.check:
        try:
            device = api.heartbeat()
            if device["device_id"] != config.DEVICE_ID:
                raise ValueError("Configured device does not match authenticated device")
            print("Agent enrollment verified.")
        except (httpx.HTTPError, ValueError):
            print("Agent connection failed; check the backend URL, device ID, and token.")
            raise SystemExit(1) from None
        finally:
            api.close()
        return
    pending = {}
    failures = 0
    try:
        while True:
            try:
                completed_install = run_once(api, config.DEVICE_ID, pending)
                failures = 0
                if completed_install and not args.once:
                    print("Installation verified and reported. Stopping endpoint agent.")
                    raise SystemExit(10)
                print("Heartbeat and task cycle completed.")
            except (httpx.HTTPError, ValueError):
                failures = min(failures + 1, 6)
                print("Agent cycle failed; check connectivity, device configuration, and backend status.")
                if args.once:
                    raise SystemExit(1) from None
            if args.once:
                break
            time.sleep(min(config.POLL_SECONDS * 2 ** failures, 60))
    finally:
        api.close()

if __name__ == "__main__":
    main()
