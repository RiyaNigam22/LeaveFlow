"""SQLAlchemy ORM models – the single source of truth for the relational schema."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, LargeBinary,
    Numeric, String, Text, UniqueConstraint, false, func, true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from utils.dates import now_utc
from workflows.states import RequestStatus, Stage, StepStatus


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, server_default=func.now(), nullable=False)


def _in(column: str, enum_cls) -> str:
    return f"{column} IN ({', '.join(repr(e.value) for e in enum_cls)})"


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    description: Mapped[str | None] = mapped_column(String(200))


class Department(TimestampMixin, Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    head_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", use_alter=True, name="fk_departments_head_employee"))

    head: Mapped["Employee | None"] = relationship(foreign_keys=[head_employee_id], post_update=True)
    employees: Mapped[list["Employee"]] = relationship(
        back_populates="department", foreign_keys="Employee.department_id")


class Employee(TimestampMixin, Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(20), unique=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(160), unique=True)
    job_title: Mapped[str | None] = mapped_column(String(120))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), index=True)
    hire_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    department: Mapped[Department] = relationship(back_populates="employees", foreign_keys=[department_id])
    manager: Mapped["Employee | None"] = relationship(remote_side=[id], back_populates="reports")
    reports: Mapped[list["Employee"]] = relationship(back_populates="manager")
    user: Mapped["User | None"] = relationship(back_populates="employee", uselist=False)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    role: Mapped[Role] = relationship()
    employee: Mapped[Employee] = relationship(back_populates="user")


class LeaveType(TimestampMixin, Base):
    __tablename__ = "leave_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(String(300))
    annual_allowance: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=0)
    tracks_balance: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    requires_document: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Document is required when the request's working days are greater than this threshold.
    document_threshold_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    document_description: Mapped[str] = mapped_column(
        String(80), default="Supporting documentation", server_default="Supporting documentation")
    can_carry_forward: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    carry_forward_limit: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=0, server_default="0")
    max_consecutive_days: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    __table_args__ = (
        CheckConstraint("annual_allowance >= 0", name="ck_leave_types_allowance"),
        CheckConstraint("max_consecutive_days IS NULL OR max_consecutive_days > 0", name="ck_leave_types_max_days"),
    )


class LeaveBalance(TimestampMixin, Base):
    __tablename__ = "leave_balances"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id"))
    year: Mapped[int] = mapped_column(Integer)
    allocated: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0)
    carried_forward: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0, server_default="0")
    used: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0, server_default="0")
    pending: Mapped[Decimal] = mapped_column(Numeric(6, 1), default=0, server_default="0")

    employee: Mapped[Employee] = relationship()
    leave_type: Mapped[LeaveType] = relationship()

    __table_args__ = (
        UniqueConstraint("employee_id", "leave_type_id", "year", name="uq_balance_employee_type_year"),
        CheckConstraint("used >= 0 AND pending >= 0", name="ck_balance_non_negative"),
    )

    @property
    def total(self) -> Decimal:
        return (self.allocated or 0) + (self.carried_forward or 0)

    @property
    def available(self) -> Decimal:
        return self.total - (self.used or 0) - (self.pending or 0)


class Holiday(TimestampMixin, Base):
    __tablename__ = "holidays"
    id: Mapped[int] = mapped_column(primary_key=True)
    holiday_date: Mapped[date] = mapped_column(Date, unique=True)
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class ApprovalRule(TimestampMixin, Base):
    """Configurable approval-level policy: applies when working days > min_days."""
    __tablename__ = "approval_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    min_days: Mapped[int] = mapped_column(Integer, unique=True)
    stages: Mapped[str] = mapped_column(String(100))  # comma separated Stage values
    description: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (CheckConstraint("min_days >= 0", name="ck_approval_rules_min_days"),)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(200))


class LeaveRequest(TimestampMixin, Base):
    __tablename__ = "leave_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    working_days: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    document_name: Mapped[str | None] = mapped_column(String(200))
    document_content: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(30), default=RequestStatus.DRAFT.value)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)

    employee: Mapped[Employee] = relationship()
    leave_type: Mapped[LeaveType] = relationship()
    steps: Mapped[list["ApprovalStep"]] = relationship(
        back_populates="request", order_by="ApprovalStep.step_order", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_request_dates"),
        CheckConstraint("working_days >= 0", name="ck_request_days"),
        CheckConstraint(_in("status", RequestStatus), name="ck_request_status"),
        Index("ix_requests_employee_status", "employee_id", "status"),
        Index("ix_requests_dates", "start_date", "end_date"),
    )


class ApprovalStep(TimestampMixin, Base):
    __tablename__ = "approval_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("leave_requests.id", ondelete="CASCADE"))
    step_order: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(30))
    # NULL approver_employee_id means "any HR/Admin user" (HR stage or manager fallback).
    approver_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    status: Mapped[str] = mapped_column(String(20), default=StepStatus.WAITING.value)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    comments: Mapped[str | None] = mapped_column(Text)

    request: Mapped[LeaveRequest] = relationship(back_populates="steps")
    approver: Mapped[Employee | None] = relationship(foreign_keys=[approver_employee_id])
    acted_by: Mapped[User | None] = relationship(foreign_keys=[acted_by_user_id])

    __table_args__ = (
        UniqueConstraint("request_id", "step_order", name="uq_step_request_order"),
        CheckConstraint(_in("stage", Stage), name="ck_step_stage"),
        CheckConstraint(_in("status", StepStatus), name="ck_step_status"),
        Index("ix_steps_approver_status", "approver_employee_id", "status"),
    )


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(150))
    message: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("leave_requests.id", ondelete="SET NULL"))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, server_default=func.now())

    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    old_value: Mapped[dict | None] = mapped_column(JSON)
    new_value: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, server_default=func.now())

    user: Mapped[User | None] = relationship()

    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )
