from typing import Literal
from datetime import date, datetime
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Login(Input):
    identifier: str = Field(min_length=1, max_length=150, validation_alias=AliasChoices('identifier', 'email'))
    password: SecretStr = Field(min_length=1, max_length=256)
    expected_role: Literal['employee', 'admin'] | None = None
    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, value):
        return value.strip().lower()

class Register(Input):
    account_role: Literal['employee', 'admin'] = 'employee'
    admin_invite_code: SecretStr | None = Field(default=None, max_length=256)
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    date_of_birth: date
    username: str = Field(min_length=3, max_length=50, pattern=r'^[a-zA-Z][a-zA-Z0-9._-]*$')
    email: str = Field(min_length=3, max_length=150)
    password: SecretStr = Field(min_length=6, max_length=256)
    confirm_password: SecretStr
    @field_validator('first_name', 'last_name')
    @classmethod
    def strip_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Name is required')
        return value
    @field_validator('username')
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower()
    @field_validator('email')
    @classmethod
    def email_format(cls, value):
        value = value.strip().lower()
        if '@' not in value or '.' not in value.split('@')[-1]:
            raise ValueError('A valid email is required')
        return value
    @field_validator('date_of_birth')
    @classmethod
    def past_birth_date(cls, value):
        if value >= date.today():
            raise ValueError('Enter a date of birth in the past')
        return value
    @field_validator("password")
    @classmethod
    def password_length(cls, value):
        if len(value.get_secret_value()) < 6:
            raise ValueError("Use at least 6 characters")
        return value
    @model_validator(mode='after')
    def passwords_match(self):
        if self.password.get_secret_value() != self.confirm_password.get_secret_value():
            raise ValueError('Passwords do not match')
        return self

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    role: str
    username: str | None
    first_name: str | None
    last_name: str | None

class UserUpdate(Input):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=150)
    @field_validator('email')
    @classmethod
    def validate_email(cls, value):
        return Register.email_format(value)

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
    original_message: str
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

class PasswordActionOut(BaseModel):
    request_id: int
    status: Literal["AWAITING_USER_ACTION"]
    url: str
    message: str

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
