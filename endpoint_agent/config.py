import os
from urllib.parse import urlparse
from dotenv import load_dotenv
load_dotenv()
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")
DEVICE_ID = os.getenv("DEVICE_ID", "")
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
SIMULATION = os.getenv("AGENT_SIMULATION_MODE", "true").lower() == "true"
def validate():
    parsed = urlparse(SERVER_URL)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")):
        raise ValueError("Use HTTPS except on localhost")
    if not DEVICE_ID or not AGENT_TOKEN:
        raise ValueError("Configure DEVICE_ID and AGENT_TOKEN")
