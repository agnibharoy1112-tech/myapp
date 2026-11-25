import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="Loan Approval Workflow")

ROLES = ("coordinator", "approver_level_1", "approver_level_2", "finance", "admin")
ROLE_LABELS = {
    "coordinator": "Loan Coordinator",
    "approver_level_1": "Loan Approval Level 1",
    "approver_level_2": "Loan Approval Level 2",
    "finance": "Finance - Fund Disbursement",
    "admin": "Admin",
}
COOKIE_NAME = "loan_staff_session"
SESSION_SECRET = os.environ.get("SESSION_SECRET", "").encode() or secrets.token_bytes(32)
SESSION_LIFETIME = 8 * 60 * 60
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class LoanApplicationInput(BaseModel):
    applicant_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    amount: float = Field(gt=0, le=10_000_000)
    purpose: str = Field(min_length=10, max_length=2000)


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class StaffUserInput(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=12, max_length=128)
    role: str


class LoanActionInput(BaseModel):
    action: str
    note: str = Field(default="", max_length=2000)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> str:
    return os.environ.get("LOAN_DB_PATH", str(Path.cwd() / "loan_workflow.sqlite3"))


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    path = db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        initialize_database(connection)
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{salt.hex()}:{digest.hex()}"


def password_matches(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return hmac.compare_digest(actual, expected)


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS staff_users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS applications (
            id TEXT PRIMARY KEY,
            tracking_code TEXT NOT NULL UNIQUE,
            applicant_name TEXT NOT NULL,
            email TEXT NOT NULL,
            amount REAL NOT NULL,
            purpose TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS application_events (
            id INTEGER PRIMARY KEY,
            application_id TEXT NOT NULL REFERENCES applications(id),
            actor TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )
    admin_username = os.environ.get("LOAN_ADMIN_USERNAME")
    admin_password = os.environ.get("LOAN_ADMIN_PASSWORD")
    if bool(admin_username) != bool(admin_password):
        raise RuntimeError("Set both LOAN_ADMIN_USERNAME and LOAN_ADMIN_PASSWORD to bootstrap the admin.")
    if admin_username and admin_password:
        existing = connection.execute(
            "SELECT id FROM staff_users WHERE username = ?", (admin_username,)
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO staff_users (username, password_hash, role, created_at) VALUES (?, ?, 'admin', ?)",
                (admin_username, password_hash(admin_password), now_iso()),
            )


def encode_session(username: str) -> str:
    payload = json.dumps(
        {"username": username, "expires": int(datetime.now(timezone.utc).timestamp()) + SESSION_LIFETIME},
        separators=(",", ":"),
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(SESSION_SECRET, encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def session_username(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE_NAME, "")
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(SESSION_SECRET, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = encoded + "=" * (-len(encoded) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        if int(data["expires"]) < int(datetime.now(timezone.utc).timestamp()):
            return None
        username = data["username"]
        return username if isinstance(username, str) else None
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def current_staff(request: Request) -> dict:
    username = session_username(request)
    if username is None:
        raise HTTPException(status_code=401, detail="Staff login required.")
    with database() as connection:
        staff = connection.execute(
            "SELECT username, role FROM staff_users WHERE username = ? AND active = 1",
            (username,),
        ).fetchone()
    if staff is None:
        raise HTTPException(status_code=401, detail="Staff login required.")
    return dict(staff)


def staff_with_roles(*roles: str):
    def check_role(staff: dict = Depends(current_staff)) -> dict:
        if staff["role"] not in roles:
            raise HTTPException(status_code=403, detail="This staff role cannot perform that action.")
        return staff

    return check_role


def application_details(connection: sqlite3.Connection, application: sqlite3.Row) -> dict:
    events = connection.execute(
        """SELECT actor, role, action, from_status, to_status, note, created_at
           FROM application_events WHERE application_id = ? ORDER BY id""",
        (application["id"],),
    ).fetchall()
    result = dict(application)
    result.pop("tracking_code", None)
    result["events"] = [dict(event) for event in events]
    return result


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/applications", status_code=201)
def submit_application(payload: LoanApplicationInput) -> dict:
    if "@" not in payload.email or "." not in payload.email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    application_id = str(uuid.uuid4())
    tracking_code = secrets.token_urlsafe(24)
    created_at = now_iso()
    with database() as connection:
        connection.execute(
            """INSERT INTO applications
               (id, tracking_code, applicant_name, email, amount, purpose, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'coordinator_review', ?, ?)""",
            (
                application_id,
                tracking_code,
                payload.applicant_name.strip(),
                payload.email.strip(),
                payload.amount,
                payload.purpose.strip(),
                created_at,
                created_at,
            ),
        )
        connection.execute(
            """INSERT INTO application_events
               (application_id, actor, role, action, from_status, to_status, created_at)
               VALUES (?, 'Customer', 'customer', 'submitted', NULL, 'coordinator_review', ?)""",
            (application_id, created_at),
        )
    return {
        "application_id": application_id,
        "tracking_code": tracking_code,
        "status": "coordinator_review",
        "message": "Application received. Save your tracking code to check its status.",
    }


@app.get("/api/track/{tracking_code}")
def track_application(tracking_code: str) -> dict:
    with database() as connection:
        application = connection.execute(
            """SELECT applicant_name, amount, status, created_at, updated_at
               FROM applications WHERE tracking_code = ?""",
            (tracking_code,),
        ).fetchone()
    if application is None:
        raise HTTPException(status_code=404, detail="No application matches that tracking code.")
    return dict(application)


@app.post("/api/login")
def login(payload: LoginInput, response: Response) -> dict:
    with database() as connection:
        staff = connection.execute(
            "SELECT username, password_hash, role FROM staff_users WHERE username = ? AND active = 1",
            (payload.username,),
        ).fetchone()
    if staff is None or not password_matches(payload.password, staff["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    response.set_cookie(
        COOKIE_NAME,
        encode_session(staff["username"]),
        httponly=True,
        secure=os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
        samesite="lax",
        max_age=SESSION_LIFETIME,
        path="/",
    )
    return {"username": staff["username"], "role": staff["role"], "role_label": ROLE_LABELS[staff["role"]]}


@app.post("/api/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"message": "Logged out."}


@app.get("/api/me")
def me(staff: dict = Depends(current_staff)) -> dict:
    return {**staff, "role_label": ROLE_LABELS[staff["role"]]}


@app.get("/api/applications")
def list_applications(staff: dict = Depends(current_staff)) -> list:
    with database() as connection:
        applications = connection.execute("SELECT * FROM applications ORDER BY created_at DESC").fetchall()
        return [application_details(connection, application) for application in applications]


@app.post("/api/applications/{application_id}/actions")
def act_on_application(
    application_id: str,
    payload: LoanActionInput,
    staff: dict = Depends(staff_with_roles("coordinator", "approver_level_1", "approver_level_2", "finance")),
) -> dict:
    transitions = {
        ("coordinator", "coordinator_review", "forward"): "level_1_review",
        ("coordinator", "coordinator_review", "reject"): "rejected",
        ("approver_level_1", "level_1_review", "approve"): "level_2_review",
        ("approver_level_1", "level_1_review", "reject"): "rejected",
        ("approver_level_2", "level_2_review", "approve"): "finance_pending",
        ("approver_level_2", "level_2_review", "reject"): "rejected",
        ("finance", "finance_pending", "disburse"): "funded",
    }
    if payload.action == "reject" and not payload.note.strip():
        raise HTTPException(status_code=422, detail="Add a reason when rejecting an application.")
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        application = connection.execute(
            "SELECT id, status FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if application is None:
            raise HTTPException(status_code=404, detail="Application not found.")
        next_status = transitions.get((staff["role"], application["status"], payload.action))
        if next_status is None:
            raise HTTPException(status_code=409, detail="This action is not available for your role at this stage.")
        updated_at = now_iso()
        connection.execute(
            "UPDATE applications SET status = ?, updated_at = ? WHERE id = ?",
            (next_status, updated_at, application_id),
        )
        connection.execute(
            """INSERT INTO application_events
               (application_id, actor, role, action, from_status, to_status, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                application_id,
                staff["username"],
                staff["role"],
                payload.action,
                application["status"],
                next_status,
                payload.note.strip(),
                updated_at,
            ),
        )
        updated = connection.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        return application_details(connection, updated)


@app.post("/api/staff", status_code=201)
def create_staff_user(
    payload: StaffUserInput,
    staff: dict = Depends(staff_with_roles("admin")),
) -> dict:
    if not payload.username.isascii() or not all(
        character.isalnum() or character in "_.-" for character in payload.username
    ):
        raise HTTPException(status_code=422, detail="Username can contain only letters, numbers, dots, underscores, and hyphens.")
    if payload.role not in ROLES:
        raise HTTPException(status_code=422, detail="Choose a supported staff role.")
    try:
        with database() as connection:
            cursor = connection.execute(
                """INSERT INTO staff_users (username, password_hash, role, created_at)
                   VALUES (?, ?, ?, ?)""",
                (payload.username, password_hash(payload.password), payload.role, now_iso()),
            )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="That username is already in use.") from error
    return {"id": cursor.lastrowid, "username": payload.username, "role": payload.role}


def run() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
