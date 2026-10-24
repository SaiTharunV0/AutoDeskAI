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
    message: str = Field(min_length=1, max_length=2000)
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
    resolved: bool | None = None
    resolution_reporter: str | None = None
    rejection_source: str | None = None
    password_action_opened_at: datetime | None = None
    resolution_attempts: int = 0
    created_at: datetime
    updated_at: datetime
    task: TaskOut | None

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: int
    kind: str
    title: str
    message: str
    created_at: datetime
    read_at: datetime | None

class AuditRequestOut(RequestOut):
    username: str

class ChatOut(BaseModel):
    id: None = None
    intent: Literal["CHAT"] = "CHAT"
    status: Literal["CHAT"] = "CHAT"
    message: str

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

class ApplicationIn(Input):
    key: str = Field(min_length=2, max_length=80, pattern=r'^[a-z][a-z0-9_-]*$')
    display_name: str = Field(min_length=2, max_length=100)
    description: str = Field(default='', max_length=500)
    enabled: bool = True
    required_role: Literal['employee', 'admin'] = 'employee'
    requestable_roles: list[str] = Field(min_length=1, max_length=20)
    allowed_groups: list[str] = Field(default_factory=list, max_length=20)
    default_duration_days: int = Field(ge=1, le=365)
    max_duration_days: int = Field(ge=1, le=365)
    approval_mode: Literal['AUTOMATIC', 'CONDITIONAL', 'ADMIN_ONLY'] = 'ADMIN_ONLY'
    conditions: dict = Field(default_factory=dict)
    fallback: Literal['REQUIRE_ADMIN_APPROVAL', 'DENY'] = 'REQUIRE_ADMIN_APPROVAL'
    human_roles: list[str] = Field(default_factory=list)
    risk: Literal['LOW', 'MEDIUM', 'HIGH'] = 'LOW'
    provider_type: Literal['MOCK', 'NONE'] = 'MOCK'
    config_ref: str = Field(default='', max_length=100, pattern=r'^[A-Z][A-Z0-9_]*$|^$')
    auto_allowed: bool = False

    @model_validator(mode='after')
    def policy_rules(self):
        roles = self.requestable_roles
        if len(set(roles)) != len(roles) or any(not role or len(role) > 50 or not role.replace('_', '').replace('-', '').isalnum() for role in roles):
            raise ValueError('Use unique simple role names')
        if any(role not in roles for role in self.human_roles):
            raise ValueError('Human approval roles must be requestable')
        if self.default_duration_days > self.max_duration_days:
            raise ValueError('Default duration exceeds maximum')
        allowed = {'min_justification_length', 'max_duration_days', 'require_verified_mfa', 'required_groups', 'employment_status'}
        if set(self.conditions) - allowed:
            raise ValueError('Unsupported policy condition')
        if any(not isinstance(group, str) or not group or len(group) > 80 for group in self.allowed_groups):
            raise ValueError('Invalid group')
        if 'min_justification_length' in self.conditions and (type(self.conditions['min_justification_length']) is not int or not 0 <= self.conditions['min_justification_length'] <= 500):
            raise ValueError('Invalid justification condition')
        if 'max_duration_days' in self.conditions and (type(self.conditions['max_duration_days']) is not int or not 1 <= self.conditions['max_duration_days'] <= 365):
            raise ValueError('Invalid duration condition')
        if 'require_verified_mfa' in self.conditions and type(self.conditions['require_verified_mfa']) is not bool:
            raise ValueError('Invalid MFA condition')
        if 'required_groups' in self.conditions and (not isinstance(self.conditions['required_groups'], list)
                or len(self.conditions['required_groups']) > 20
                or any(not isinstance(g, str) or not g or len(g) > 80 for g in self.conditions['required_groups'])):
            raise ValueError('Invalid group condition')
        if 'employment_status' in self.conditions and self.conditions['employment_status'] != 'ACTIVE':
            raise ValueError('Unsupported employment condition')
        return self

class AccessSubmit(Input):
    application: str = Field(min_length=2, max_length=80)
    requested_role: str = Field(min_length=1, max_length=50)
    justification: str = Field(default='', max_length=500)
    duration_days: int = Field(ge=1, le=365)
    idempotency_key: str = Field(min_length=8, max_length=100)

class AccessDecisionIn(Input):
    decision: Literal['APPROVE', 'REJECT']
    reason: str = Field(default='', max_length=200)

class TicketClosureSettingIn(Input):
    mode: Literal['AUTOMATIC', 'ADMIN_CONFIRMATION']

class TicketCloseIn(Input):
    resolved: bool

class TicketRejectIn(Input):
    reason: str = Field(min_length=5, max_length=200)

class TicketResolutionOut(BaseModel):
    request_id: int
    status: str
    resolved: bool | None
    resolution_reporter: str | None
    resolution_attempts: int
    escalated: bool = False
    retry_action: bool = False
    message: str

class AccessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: int
    user_id: int
    application: str
    requested_role: str
    justification: str
    duration_days: int
    status: str
    approval_route: str
    policy_version: int
    evaluation_json: str
    decision_reason: str
    provisioning_status: str
    expires_at: datetime | None
    approver_id: int | None
    decision_at: datetime | None
    created_at: datetime
    provision_attempts: int
    last_provision_attempt_at: datetime | None
    provisioned_at: datetime | None
