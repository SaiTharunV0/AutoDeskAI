"""Reports availability only; never prints configuration values or exception bodies."""
import os
import httpx
import config
from sqlalchemy import create_engine, text
print("JWT configured:", len(config.JWT_SECRET_KEY) >= 32)
print("Database environment configured:", "DATABASE_URL" in os.environ)
try:
    engine = create_engine(config.DATABASE_URL, connect_args={"connect_timeout": 5})
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    print("Database reachable: yes")
except Exception as error:
    print("Database check:", type(error).__name__)
try:
    response = httpx.get(config.OLLAMA_HOST + "/api/tags", timeout=5)
    print("Ollama status:", response.status_code)
    print("Configured model present:", any(m["name"] == config.OLLAMA_MODEL for m in response.json().get("models", [])))
except Exception as error:
    print("Ollama check:", type(error).__name__)
