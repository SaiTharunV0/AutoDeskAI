from typing import Optional
from enum import Enum
from pydantic import BaseModel


class Intent(str, Enum):
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    PASSWORD_RESET = "PASSWORD_RESET"
    SOFTWARE_INSTALL = "SOFTWARE_INSTALL"
    ACCESS_REQUEST = "ACCESS_REQUEST"

    CHAT = "CHAT"
    CLARIFICATION = "CLARIFICATION"


class AgentResponse(BaseModel):
    intent: Intent

    software: Optional[str] = None
    application: Optional[str] = None

    message: str