import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
# A frozen executable extracts its modules into a temporary directory. Read
# configuration beside the installed executable instead of that directory.
if getattr(sys, 'frozen', False):
    load_dotenv(dotenv_path=Path(sys.executable).resolve().parent / '.env')
else:
    load_dotenv()
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")
DEVICE_ID = os.getenv("DEVICE_ID", "")
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
INSTALL_MODE = os.getenv("AGENT_INSTALL_MODE", "disabled").lower()
POLL_SECONDS = float(os.getenv("AGENT_POLL_SECONDS", "10"))
def validate():
    parsed = urlparse(SERVER_URL)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")):
        raise ValueError("Use HTTPS except on localhost")
    if not DEVICE_ID or not AGENT_TOKEN:
        raise ValueError("Configure DEVICE_ID and AGENT_TOKEN")
    if not 1 <= POLL_SECONDS <= 60:
        raise ValueError("AGENT_POLL_SECONDS must be between 1 and 60 seconds")
    if INSTALL_MODE != "real":
        raise ValueError("Set AGENT_INSTALL_MODE=real to enable live endpoint installations")
