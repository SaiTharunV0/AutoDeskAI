from typing import Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Login(Input):
    email: str = Field(max_length=150)
    password: SecretStr = Field(min_length=1, max_length=256)
    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        value = value.strip().lower()
        if "@" not in value or "." not in value.split("@")[-1]:
            raise ValueError("A valid email is required")
        return value

class Register(Login):
    name: str = Field(min_length=1, max_length=100)
    @field_validator("password")
    @classmethod
    def password_length(cls, value):
        if len(value.get_secret_value()) < 12:
            raise ValueError("Use at least 12 characters")
        return value

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    role: str

class UserUpdate(Input):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=150)
    @field_validator('email')
    @classmethod
    def validate_email(cls, value):
        return Login.email_format(value)

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class RequestIn(Input):
    message: str = Field(min_length=1, max_length=1000)
    device_id: int | None = None
    previous_request_id: int | None = None
    idempotency_key: str = Field(min_length=8, max_length=100)

class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    software: str
    status: str
    result: str | None

class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    intent: str
    status: str
    message: str
    created_at: datetime
    updated_at: datetime
    task: TaskOut | None

class DeviceIn(Input):
    device_id: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    hostname: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    os_info: Literal["Windows", "Linux", "Darwin", "Test"] = "Windows"
    owner_user_id: int | None = None

class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: str
    hostname: str
    owner_user_id: int
    status: str
    last_seen: datetime
    os_info: str

class DeviceEnrollment(BaseModel):
    device: DeviceOut
    agent_token: str

class ResultIn(Input):
    success: bool
    simulated: bool = True

class PolicyIn(Input):
    enabled: bool
    required_role: Literal["employee", "admin"] = "employee"

class DeviceState(Input):
    status: Literal["ACTIVE", "DISABLED"]

class PasswordConfirm(Input):
    confirm_simulation: Literal[True]

class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    action: str
    resource_type: str
    resource_id: int | None
    status: str
    details: str
    timestamp: datetime
