"""Run with python -m endpoint_agent.agent. Enrollment is administrator-controlled."""
import argparse
import time
import httpx
from endpoint_agent import config
from endpoint_agent.api import AgentAPI
from endpoint_agent.installer import install

def run_once(api, device_id, simulation=True, pending=None):
    pending = pending if pending is not None else {}
    device = api.heartbeat()
    if device["device_id"] != device_id:
        raise ValueError("Configured device does not match authenticated device")
    # Retry results before claiming more work. Backend result handling is idempotent.
    for task_id, result in list(pending.items()):
        api.report(task_id, result)
        del pending[task_id]
    for task in api.tasks():
        if task["device_id"] != device["id"] or task["status"] != "PROCESSING":
            raise ValueError("Task does not belong to this registered device")
        try:
            result = install(task["software"], simulation)
        except ValueError:
            result = {"success": False, "simulated": True}
        pending[task["id"]] = result
        api.report(task["id"], result)
        del pending[task["id"]]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config.validate()
    api = AgentAPI(config.SERVER_URL, config.AGENT_TOKEN)
    pending = {}
    try:
        while True:
            try:
                run_once(api, config.DEVICE_ID, config.SIMULATION, pending)
                print("Heartbeat and task cycle completed.")
            except (httpx.HTTPError, ValueError):
                print("Agent cycle failed; check connectivity, device configuration, and backend status.")
                if args.once:
                    raise SystemExit(1) from None
            if args.once:
                break
            time.sleep(5)
    finally:
        api.close()

if __name__ == "__main__":
    main()
