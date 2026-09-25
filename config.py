"""Central configuration; never print credential values."""
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / '.env', override=False)
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg://localhost/autodeskaidb')
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', '')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_EXPIRE_MINUTES = int(os.getenv('JWT_EXPIRE_MINUTES', '60'))
OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen3:8b')
OLLAMA_TIMEOUT = int(os.getenv('OLLAMA_TIMEOUT', '90'))
TASK_TIMEOUT_SECONDS = int(os.getenv('TASK_TIMEOUT_SECONDS', '600'))
DEVICE_OFFLINE_SECONDS = int(os.getenv('DEVICE_OFFLINE_SECONDS', '120'))
