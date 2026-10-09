from typing import Optional
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class Intent(str, Enum):
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    PASSWORD_RESET = "PASSWORD_RESET"
    SOFTWARE_INSTALL = "SOFTWARE_INSTALL"
    ACCESS_REQUEST = "ACCESS_REQUEST"

    CHAT = "CHAT"
    CLARIFICATION = "CLARIFICATION"


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent

    software: Optional[str] = Field(default=None, max_length=80)
    application: Optional[str] = Field(default=None, max_length=80)

    message: str = Field(max_length=500)

class LoginRequest(BaseModel):
    email: str
    password: str
