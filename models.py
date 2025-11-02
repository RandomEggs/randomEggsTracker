from datetime import datetime, timezone, timedelta

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


IST = timezone(timedelta(hours=5, minutes=30))


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_utc_iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return _ensure_utc(dt).isoformat()


def to_ist_string(dt: datetime | None) -> str | None:
    if not dt:
        return None
    ist_dt = _ensure_utc(dt).astimezone(IST)
    return ist_dt.strftime("%d %b %Y, %I:%M %p IST")


def to_ist_datetime(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    return _ensure_utc(dt).astimezone(IST)


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), nullable=False, default="pending")
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    pomodoro_sessions = db.relationship(
        "PomodoroSession", back_populates="task", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "status": self.status,
            "created_at": to_utc_iso(self.created_at),
            "created_at_ist": to_ist_string(self.created_at),
        }


class PomodoroSession(db.Model):
    __tablename__ = "pomodoro_sessions"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    start_time = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    end_time = db.Column(db.DateTime, nullable=True)
    duration = db.Column(db.Integer, nullable=True)  # duration in seconds

    task = db.relationship("Task", back_populates="pomodoro_sessions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "start_time": to_utc_iso(self.start_time),
            "end_time": to_utc_iso(self.end_time),
            "start_time_ist": to_ist_string(self.start_time),
            "end_time_ist": to_ist_string(self.end_time),
            "duration": self.duration,
        }


class User(db.Model):
    __tablename__ = "users"
    __bind_key__ = "auth"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_active_at = db.Column(db.DateTime, nullable=True)

    activity_logs = db.relationship(
        "ActivityLog", back_populates="user", cascade="all, delete-orphan"
    )


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    __bind_key__ = "auth"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    action = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user = db.relationship("User", back_populates="activity_logs")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action": self.action,
            "description": self.description,
            "details": self.details or {},
            "created_at": to_utc_iso(self.created_at),
            "created_at_ist": to_ist_string(self.created_at),
        }
