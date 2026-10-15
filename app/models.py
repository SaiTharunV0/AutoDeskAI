from datetime import date, datetime, timezone
from sqlalchemy import String, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(nullable=True)
    username: Mapped[str | None] = mapped_column(String(50), unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="employee")
    devices: Mapped[list["Device"]] = relationship(back_populates="owner")
    requests: Mapped[list["HelpdeskRequest"]] = relationship(back_populates="user")

class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (Index("ix_devices_owner", "owner_user_id"),
                      Index("ix_devices_token", "token_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(100), unique=True)
    hostname: Mapped[str] = mapped_column(String(100))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    last_seen: Mapped[datetime] = mapped_column(default=now)
    os_info: Mapped[str] = mapped_column(String(100))
    owner: Mapped[User] = relationship(back_populates="devices")

class HelpdeskRequest(Base):
    __tablename__ = "helpdesk_requests"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),
                      Index("ix_requests_user_id", "user_id", "id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    intent: Mapped[str] = mapped_column(String(30))
    original_message: Mapped[str] = mapped_column(String(200), default="[not retained]")
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    message: Mapped[str] = mapped_column(String(500), default="")
    idempotency_key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)
    user: Mapped[User] = relationship(back_populates="requests")
    task: Mapped["SoftwareTask | None"] = relationship(back_populates="request", uselist=False)
    access: Mapped["AccessRequest | None"] = relationship(back_populates="request", uselist=False)

class SoftwareTask(Base):
    __tablename__ = "software_tasks"
    __table_args__ = (Index("ix_tasks_status_created", "status", "created_at"),
                      Index("ix_tasks_device_status", "device_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("helpdesk_requests.id"), unique=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    software: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    result: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    request: Mapped[HelpdeskRequest] = relationship(back_populates="task")
    device: Mapped[Device] = relationship()

class AccessRequest(Base):
    __tablename__ = "access_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("helpdesk_requests.id"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    application: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30))
    decision_reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now)
    request: Mapped[HelpdeskRequest] = relationship(back_populates="access")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_resource", "resource_type", "resource_id", "id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(30))
    details: Mapped[str] = mapped_column(String(200), default="")
    timestamp: Mapped[datetime] = mapped_column(default=now)

class SoftwarePolicy(Base):
    __tablename__ = "software_policies"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)

class ApplicationPolicy(Base):
    __tablename__ = "application_policies"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    required_role: Mapped[str] = mapped_column(String(30), default="employee")
