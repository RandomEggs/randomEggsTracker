from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from typing import List

from functools import wraps
from collections import OrderedDict

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from models import (
    ActivityLog,
    PomodoroSession,
    Task,
    User,
    db,
    to_ist_datetime,
    to_ist_string,
    to_utc_iso,
    IST,
)


BASE_DIR = Path(__file__).resolve().parent


def ensure_admin_user() -> None:
    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(
            username="admin",
            email=None,
            password_hash=generate_password_hash("Cycerzzz"),
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    primary_db_url = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'productivity.db'}"
    )
    auth_db_url = os.environ.get("AUTH_DATABASE_URL", primary_db_url)

    app.config["SQLALCHEMY_DATABASE_URI"] = primary_db_url
    app.config["SQLALCHEMY_BINDS"] = {
        "auth": auth_db_url,
    }
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    auto_init = os.environ.get("INIT_DB_ON_STARTUP", "true").lower() == "true"
    if auto_init:
        with app.app_context():
            db.create_all()
            db.create_all(bind_key="auth")
            ensure_admin_user()

    register_routes(app)
    return app


def register_routes(app: Flask) -> None:
    def login_required(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if session.get("user_id") is None:
                next_url = request.path if request.method == "GET" else url_for("dashboard")
                return redirect(url_for("login", next=next_url))
            return view(*args, **kwargs)

        return wrapped_view

    def login_required_json(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if session.get("user_id") is None:
                return jsonify({"error": "Authentication required"}), 401
            return view(*args, **kwargs)

        return wrapped_view

    def admin_required(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not g.user or not g.user.is_admin:
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    def login_user(user: User) -> None:
        session["user_id"] = user.id
        session.permanent = True
        now_utc = datetime.now(timezone.utc)
        user.last_login_at = now_utc
        user.last_active_at = now_utc
        db.session.commit()

    ROUTINE_ACTIONS = {"view_dashboard", "view_admin_panel"}

    def track_activity(action: str, description: str | None = None, details: dict | None = None) -> None:
        if not g.user:
            return
        g.user.last_active_at = datetime.now(timezone.utc)
        if action in ROUTINE_ACTIONS:
            db.session.commit()
            return
        entry = ActivityLog(
            user_id=g.user.id,
            action=action,
            description=description,
            details=details or {},
        )
        db.session.add(entry)
        db.session.commit()

    def logout_user() -> None:
        session.pop("user_id", None)

    @app.before_request
    def load_logged_in_user() -> None:
        user_id = session.get("user_id")
        g.user = User.query.get(user_id) if user_id else None
        if user_id and g.user is None:
            session.pop("user_id", None)

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            email = (request.form.get("email") or "").strip().lower()
            username = (request.form.get("username") or "").strip().lower()
            password = request.form.get("password")
            if not email or not password or not username:
                flash("Email, username, and password are required.", "error")
            elif User.query.filter_by(email=email).first():
                flash("An account with that email already exists.", "error")
            elif User.query.filter_by(username=username).first():
                flash("Username is already taken.", "error")
            else:
                user = User(
                    email=email,
                    username=username,
                    password_hash=generate_password_hash(password),
                )
                db.session.add(user)
                db.session.commit()
                login_user(user)
                flash("Account created successfully.", "success")
                return redirect(url_for("dashboard"))
        return render_template("signup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            identifier = (request.form.get("identifier") or "").strip()
            password = request.form.get("password") or ""
            user = None
            if identifier:
                if "@" in identifier:
                    user = User.query.filter_by(email=identifier.lower()).first()
                else:
                    user = User.query.filter_by(username=identifier.lower()).first()
            if not user or not check_password_hash(user.password_hash, password):
                flash("Invalid credentials.", "error")
            else:
                login_user(user)
                track_activity("login", "User signed in")
                next_url = request.args.get("next")
                if not next_url:
                    next_url = url_for("admin_panel") if user.is_admin else url_for("dashboard")
                return redirect(next_url)
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        if g.user:
            track_activity("logout", "User signed out")
            logout_user()
            flash("You have been logged out.", "info")
        return redirect(url_for("login"))

    @app.route("/admin")
    @login_required
    @admin_required
    def admin_panel():
        track_activity("view_admin_panel", "Viewed admin panel")
        return render_template("admin.html", current_user=g.user)

    @app.get("/admin/activity")
    @login_required
    @admin_required
    def admin_activity_feed():
        limit = min(int(request.args.get("limit", 50) or 50), 200)
        user_filter = request.args.get("user_id", type=int)
        query = (
            ActivityLog.query.join(User)
            .filter(User.is_admin.is_(False))
            .filter(~ActivityLog.action.in_(ROUTINE_ACTIONS))
        )
        if user_filter:
            query = query.filter(ActivityLog.user_id == user_filter)
        logs = query.order_by(ActivityLog.created_at.desc()).limit(limit).all()
        payload = []
        for log in logs:
            item = log.to_dict()
            item["username"] = log.user.username if log.user else "Unknown"
            payload.append(item)
        return jsonify(payload)

    @app.get("/admin/summary")
    @login_required
    @admin_required
    def admin_summary():
        users = (
            User.query.filter(User.is_admin.is_(False))
            .order_by(User.created_at.asc())
            .all()
        )
        summary = []
        for account in users:
            task_query = Task.query.filter_by(user_id=account.id)
            total_tasks = task_query.count()
            completed_tasks = task_query.filter_by(status="done").count()
            total_sessions = PomodoroSession.query.filter_by(user_id=account.id).count()
            total_focus = (
                db.session.query(func.coalesce(func.sum(PomodoroSession.duration), 0))
                .filter_by(user_id=account.id)
                .scalar()
            )
            summary.append(
                {
                    "id": account.id,
                    "username": account.username,
                    "email": account.email,
                    "is_admin": account.is_admin,
                    "created_at": to_utc_iso(account.created_at),
                    "created_at_ist": to_ist_string(account.created_at),
                    "last_login_at": account.last_login_at.isoformat()
                    if account.last_login_at
                    else None,
                    "last_login_at_ist": to_ist_string(account.last_login_at),
                    "last_active_at": account.last_active_at.isoformat()
                    if account.last_active_at
                    else None,
                    "last_active_at_ist": to_ist_string(account.last_active_at),
                    "total_tasks": total_tasks,
                    "completed_tasks": completed_tasks,
                    "total_sessions": total_sessions,
                    "total_focus_minutes": int((total_focus or 0) / 60),
                }
            )
        return jsonify(summary)

    @app.route("/profile")
    @login_required
    def profile():
        total_tasks = Task.query.filter_by(user_id=g.user.id).count()
        completed_tasks = Task.query.filter_by(user_id=g.user.id, status="done").count()
        total_sessions = PomodoroSession.query.filter_by(user_id=g.user.id).count()
        total_focus = (
            db.session.query(func.coalesce(func.sum(PomodoroSession.duration), 0))
            .filter_by(user_id=g.user.id)
            .scalar()
        )
        return render_template(
            "profile.html",
            user=g.user,
            joined_at_ist=to_ist_string(g.user.created_at),
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            total_sessions=total_sessions,
            total_focus_minutes=int((total_focus or 0) / 60),
        )

    @app.route("/")
    @login_required
    def dashboard():
        if g.user.is_admin:
            return redirect(url_for("admin_panel"))
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_tasks = (
            Task.query.filter(Task.user_id == g.user.id)
            .filter(Task.created_at >= today_start)
            .filter(Task.status != "done")
            .order_by(Task.created_at.desc())
            .all()
        )
        stats_payload = get_recent_stats(user_id=g.user.id, days=7)
        track_activity("view_dashboard", "Viewed dashboard")
        return render_template(
            "dashboard.html",
            tasks=[task.to_dict() for task in today_tasks],
            stats=stats_payload,
            work_duration_minutes=25,
            break_duration_minutes=5,
            user=g.user,
        )

    @app.get("/tasks")
    @login_required_json
    def list_tasks():
        tasks = (
            Task.query.filter(Task.user_id == g.user.id)
            .filter(Task.status != "done")
            .order_by(Task.created_at.desc())
            .all()
        )
        return jsonify([task.to_dict() for task in tasks])

    @app.route("/completed")
    @app.route("/completed-tasks")
    @login_required
    def completed_tasks_page():
        grouped = _get_completed_tasks(g.user.id)
        return render_template(
            "completed_tasks.html",
            grouped_tasks=grouped,
            user=g.user,
        )

    @app.get("/api/tasks/completed")
    @login_required_json
    def completed_tasks_api():
        grouped = _get_completed_tasks(g.user.id)
        return jsonify(grouped)

    def _get_completed_tasks(user_id: int) -> dict:
        completed = (
            Task.query.filter_by(user_id=user_id, status="done")
            .order_by(Task.created_at.desc())
            .all()
        )
        month_map: OrderedDict[str, dict] = OrderedDict()
        total = 0
        for task in completed:
            ist_dt = to_ist_datetime(task.created_at)
            if not ist_dt:
                continue
            month_label = ist_dt.strftime("%B %Y")
            day_key = ist_dt.date()
            day_label = ist_dt.strftime("%d %b %Y (%A)")
            month_entry = month_map.setdefault(
                month_label,
                {"month_label": month_label, "total_tasks": 0, "days": OrderedDict()},
            )
            day_entry = month_entry["days"].setdefault(
                day_key,
                {
                    "date_label": day_label,
                    "tasks": [],
                },
            )
            task_info = {
                "id": task.id,
                "title": task.title,
                "created_at": to_utc_iso(task.created_at),
                "created_at_ist": to_ist_string(task.created_at),
                "time_label": ist_dt.strftime("%I:%M %p"),
            }
            day_entry["tasks"].append(task_info)
            month_entry["total_tasks"] += 1
            total += 1

        months = []
        for month_entry in month_map.values():
            days = []
            for day_entry in month_entry["days"].values():
                day_entry["tasks_count"] = len(day_entry["tasks"])
                days.append(day_entry)
            month_entry["days"] = days
            months.append(month_entry)

        return {"total_completed": total, "months": months}

    @app.post("/add")
    @login_required_json
    def add_task():
        payload = request.get_json(silent=True) or request.form
        title = (payload.get("title") or "").strip()
        status = payload.get("status", "pending")
        if not title:
            return jsonify({"error": "Title is required"}), 400
        task = Task(title=title, status=status, user_id=g.user.id)
        db.session.add(task)
        db.session.commit()
        track_activity("task_created", f"Created task '{title}'", {"task_id": task.id})
        return jsonify(task.to_dict()), 201

    @app.post("/update/<int:task_id>")
    @login_required_json
    def update_task(task_id: int):
        task = Task.query.filter_by(id=task_id, user_id=g.user.id).first()
        if not task:
            abort(404)
        payload = request.get_json(silent=True) or request.form
        title = payload.get("title")
        status = payload.get("status")
        if title is not None:
            title = title.strip()
            if not title:
                return jsonify({"error": "Title cannot be empty"}), 400
            task.title = title
        if status is not None:
            task.status = status
        db.session.commit()
        track_activity(
            "task_updated",
            f"Updated task '{task.title}'",
            {"task_id": task.id, "status": task.status},
        )
        return jsonify(task.to_dict())

    @app.post("/delete/<int:task_id>")
    @login_required_json
    def delete_task(task_id: int):
        task = Task.query.filter_by(id=task_id, user_id=g.user.id).first()
        if not task:
            abort(404)
        db.session.delete(task)
        db.session.commit()
        track_activity("task_deleted", f"Deleted task '{task.title}'", {"task_id": task.id})
        return jsonify({"success": True})

    @app.post("/api/pomodoro/start")
    @login_required_json
    def start_pomodoro():
        payload = request.get_json(silent=True) or {}
        task_id = payload.get("task_id")
        if task_id is not None:
            task = Task.query.filter_by(id=task_id, user_id=g.user.id).first()
            if not task:
                return jsonify({"error": "Invalid task"}), 400
        session_record = PomodoroSession(
            task_id=task_id,
            user_id=g.user.id,
            start_time=datetime.now(timezone.utc),
        )
        db.session.add(session_record)
        db.session.commit()
        track_activity(
            "pomodoro_started",
            "Started Pomodoro session",
            {"session_id": session_record.id, "task_id": task_id},
        )
        return (
            jsonify(
                {
                    "session_id": session_record.id,
                    "start_time": session_record.start_time.isoformat(),
                }
            ),
            201,
        )

    @app.post("/api/pomodoro/end/<int:session_id>")
    @login_required_json
    def end_pomodoro(session_id: int):
        session_record = (
            PomodoroSession.query.filter_by(id=session_id, user_id=g.user.id).first()
        )
        if not session_record:
            abort(404)
        if session_record.end_time:
            return jsonify({"error": "Session already ended"}), 400
        payload = request.get_json(silent=True) or {}
        duration = payload.get("duration")
        session_record.end_time = datetime.now(timezone.utc)
        if duration is not None:
            session_record.duration = int(duration)
        elif session_record.start_time:
            session_record.duration = int(
                (session_record.end_time - session_record.start_time).total_seconds()
            )
        db.session.commit()
        track_activity(
            "pomodoro_completed",
            "Completed Pomodoro session",
            {
                "session_id": session_record.id,
                "task_id": session_record.task_id,
                "duration": session_record.duration,
            },
        )
        return jsonify(session_record.to_dict())

    @app.get("/api/pomodoro/stats")
    @login_required_json
    def pomodoro_stats():
        stats_payload = get_recent_stats(user_id=g.user.id, days=7)
        return jsonify(stats_payload)


def get_recent_stats(user_id: int | None = None, days: int = 7) -> List[dict]:
    tz_now = datetime.now(timezone.utc).astimezone(IST)
    window_start = tz_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days - 1
    )
    window_start_utc = window_start.astimezone(timezone.utc)
    query = (
        db.session.query(
            func.date(PomodoroSession.start_time).label("date"),
            func.count(PomodoroSession.id).label("sessions"),
            func.sum(PomodoroSession.duration).label("total_duration"),
        )
        .filter(PomodoroSession.start_time >= window_start_utc)
        .filter(PomodoroSession.duration.isnot(None))
    )
    if user_id is not None:
        query = query.filter(PomodoroSession.user_id == user_id)
    rows = (
        query.group_by(func.date(PomodoroSession.start_time))
        .order_by(func.date(PomodoroSession.start_time))
        .all()
    )
    stats = []
    for row in rows:
        raw_date = row.date
        if isinstance(raw_date, datetime):
            dt_utc = raw_date if raw_date.tzinfo else raw_date.replace(tzinfo=timezone.utc)
        elif isinstance(raw_date, str):
            dt_utc = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            dt_utc = datetime.combine(raw_date, time(), tzinfo=timezone.utc)
        ist_date = to_ist_datetime(dt_utc)
        date_label = ist_date.strftime("%d %b") if ist_date else str(raw_date)
        stats.append(
            {
                "date": date_label,
                "sessions": row.sessions or 0,
                "total_duration": int(row.total_duration or 0),
            }
        )
    return stats


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
