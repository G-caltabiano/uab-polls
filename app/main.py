from __future__ import annotations

import io
import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .db import db, init_db, utcnow
from .email_service import send_response_notification
from .security import (
    csrf_token,
    hash_password,
    random_token,
    token_hash,
    valid_csrf,
    verify_password,
)


APP_DIR = Path(__file__).resolve().parent
MADRID = ZoneInfo("Europe/Madrid")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    root_path=settings.root_path,
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="uab_polls_session",
    max_age=60 * 60 * 12,
    same_site="lax",
    https_only=settings.secure_cookies,
)
templates = Jinja2Templates(directory=APP_DIR / "templates")


def go(request: Request, route: str, **params) -> RedirectResponse:
    return RedirectResponse(request.url_for(route, **params), status_code=303)


def flash(request: Request, message: str, kind: str = "info") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def context(request: Request, **extra) -> dict:
    result = {
        "request": request,
        "csrf": csrf_token(request.session),
        "flash": request.session.pop("flash", None),
        "admin": None,
        "settings": settings,
    }
    admin_id = request.session.get("admin_id")
    if admin_id:
        with db() as connection:
            result["admin"] = connection.execute(
                "SELECT id, email, display_name FROM admins WHERE id=? AND active=1",
                (admin_id,),
            ).fetchone()
    result.update(extra)
    return result


def require_admin(request: Request):
    admin_id = request.session.get("admin_id")
    if not admin_id:
        raise HTTPException(status_code=401, detail="Cal iniciar sessió")
    with db() as connection:
        admin = connection.execute(
            "SELECT id, email, display_name FROM admins WHERE id=? AND active=1",
            (admin_id,),
        ).fetchone()
    if not admin:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Sessió no vàlida")
    return admin


def check_csrf(request: Request, form) -> None:
    if not valid_csrf(request.session, form.get("csrf")):
        raise HTTPException(status_code=403, detail="Formulari caducat. Torna-ho a provar.")


def local_dt(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MADRID)
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat()


def fmt_dt(value: str | None) -> str:
    if not value:
        return ""
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone(MADRID).strftime("%d/%m/%Y · %H:%M")


templates.env.filters["datetime_ca"] = fmt_dt


@app.get("/static/{path:path}", name="static", include_in_schema=False)
def static_asset(path: str) -> FileResponse:
    static_dir = (APP_DIR / "static").resolve()
    asset = (static_dir / path).resolve()
    if static_dir not in asset.parents or not asset.is_file():
        raise HTTPException(status_code=404, detail="Fitxer no trobat")
    return FileResponse(asset)


def load_poll(connection, slug: str):
    return connection.execute(
        """SELECT p.*, a.display_name AS creator_name, a.email AS creator_email
           FROM polls p JOIN admins a ON a.id=p.created_by WHERE p.slug=?""",
        (slug,),
    ).fetchone()


def load_poll_data(connection, poll_id: int) -> tuple[list, list, dict, list]:
    slots = connection.execute(
        "SELECT * FROM slots WHERE poll_id=? ORDER BY start_at", (poll_id,)
    ).fetchall()
    participants = connection.execute(
        "SELECT * FROM participants WHERE poll_id=? ORDER BY updated_at, name", (poll_id,)
    ).fetchall()
    response_rows = connection.execute(
        """SELECT r.participant_id, r.slot_id, r.choice
           FROM responses r JOIN participants p ON p.id=r.participant_id
           WHERE p.poll_id=?""",
        (poll_id,),
    ).fetchall()
    response_map = {(row["participant_id"], row["slot_id"]): row["choice"] for row in response_rows}
    summary = connection.execute(
        """SELECT s.id AS slot_id,
                  SUM(CASE WHEN r.choice='yes' THEN 1 ELSE 0 END) AS yes_count,
                  SUM(CASE WHEN r.choice='maybe' THEN 1 ELSE 0 END) AS maybe_count,
                  SUM(CASE WHEN r.choice='no' THEN 1 ELSE 0 END) AS no_count
           FROM slots s LEFT JOIN responses r ON r.slot_id=s.id
           WHERE s.poll_id=? GROUP BY s.id ORDER BY yes_count DESC, maybe_count DESC, s.start_at""",
        (poll_id,),
    ).fetchall()
    return slots, participants, response_map, summary


@app.get("/health")
def health():
    try:
        with db() as connection:
            connection.execute("SELECT 1").fetchone()
        return {
            "ok": True,
            "email_provider": settings.email_provider,
            "email_sender": settings.gog_account if settings.email_provider == "gog" else settings.smtp_from,
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with db() as connection:
        admin_count = connection.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    if request.session.get("admin_id"):
        return go(request, "admin_dashboard")
    return templates.TemplateResponse(
        "home.html", context(request, admin_count=admin_count)
    )


@app.get("/admin/setup", response_class=HTMLResponse)
def setup_form(request: Request):
    with db() as connection:
        if connection.execute("SELECT COUNT(*) FROM admins").fetchone()[0]:
            return go(request, "login_form")
    return templates.TemplateResponse("setup.html", context(request))


@app.post("/admin/setup")
async def setup_submit(request: Request):
    form = await request.form()
    check_csrf(request, form)
    name = str(form.get("name", "")).strip()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    if email != settings.initial_admin_email:
        flash(request, "El primer compte ha d'utilitzar el correu UAB autoritzat.", "error")
        return go(request, "setup_form")
    if len(name) < 2 or len(password) < 12:
        flash(request, "Indica el nom i una contrasenya d'almenys 12 caràcters.", "error")
        return go(request, "setup_form")
    with db() as connection:
        if connection.execute("SELECT COUNT(*) FROM admins").fetchone()[0]:
            return go(request, "login_form")
        cursor = connection.execute(
            "INSERT INTO admins(email,display_name,password_hash,created_at) VALUES(?,?,?,?)",
            (email, name[:100], hash_password(password), utcnow()),
        )
        request.session["admin_id"] = cursor.lastrowid
    flash(request, "Compte administrador creat.", "success")
    return go(request, "admin_dashboard")


@app.get("/admin/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", context(request))


@app.post("/admin/login")
async def login_submit(request: Request):
    form = await request.form()
    check_csrf(request, form)
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    with db() as connection:
        admin = connection.execute(
            "SELECT * FROM admins WHERE email=? AND active=1", (email,)
        ).fetchone()
    if not admin or not verify_password(password, admin["password_hash"]):
        flash(request, "Correu o contrasenya incorrectes.", "error")
        return go(request, "login_form")
    request.session.clear()
    request.session["admin_id"] = admin["id"]
    flash(request, f"Benvingut/da, {admin['display_name']}.", "success")
    return go(request, "admin_dashboard")


@app.post("/admin/logout")
async def logout(request: Request):
    form = await request.form()
    check_csrf(request, form)
    request.session.clear()
    return go(request, "home")


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    require_admin(request)
    with db() as connection:
        polls = connection.execute(
            """SELECT p.*,
                      COUNT(DISTINCT s.id) AS slot_count,
                      COUNT(DISTINCT pt.id) AS participant_count
               FROM polls p
               LEFT JOIN slots s ON s.poll_id=p.id
               LEFT JOIN participants pt ON pt.poll_id=p.id
               GROUP BY p.id ORDER BY p.created_at DESC"""
        ).fetchall()
    return templates.TemplateResponse("dashboard.html", context(request, polls=polls))


@app.get("/admin/polls/new", response_class=HTMLResponse)
def poll_new_form(request: Request):
    require_admin(request)
    return templates.TemplateResponse("poll_new.html", context(request))


@app.post("/admin/polls/new")
async def poll_new_submit(request: Request):
    admin = require_admin(request)
    form = await request.form()
    check_csrf(request, form)
    title = str(form.get("title", "")).strip()
    description = str(form.get("description", "")).strip()
    location = str(form.get("location", "")).strip()
    try:
        duration = int(form.get("duration", 0))
        raw_slots = json.loads(str(form.get("slots_json", "[]")))
    except (ValueError, TypeError, json.JSONDecodeError):
        duration, raw_slots = 0, []
    if not title or duration not in {30, 60, 90} or not raw_slots:
        flash(request, "Indica un títol, la durada i almenys una opció horària.", "error")
        return go(request, "poll_new_form")
    parsed_slots: list[tuple[str, str]] = []
    for raw in raw_slots[:100]:
        try:
            start = datetime.fromisoformat(str(raw))
            if start.tzinfo is None:
                start = start.replace(tzinfo=MADRID)
            start = start.astimezone(UTC).replace(second=0, microsecond=0)
            end = start + timedelta(minutes=duration)
            if start < datetime.now(UTC) - timedelta(minutes=5):
                continue
            parsed_slots.append((start.isoformat(), end.isoformat()))
        except (ValueError, TypeError):
            continue
    parsed_slots = sorted(set(parsed_slots))
    if not parsed_slots:
        flash(request, "Les opcions horàries no són vàlides o ja han passat.", "error")
        return go(request, "poll_new_form")
    deadline = local_dt(str(form.get("deadline", "")))
    slug = random_token(10)
    with db() as connection:
        cursor = connection.execute(
            """INSERT INTO polls(slug,title,description,location,duration_minutes,deadline_at,
                                 created_by,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (slug, title[:180], description[:3000], location[:200], duration, deadline, admin["id"], utcnow()),
        )
        poll_id = cursor.lastrowid
        connection.executemany(
            "INSERT INTO slots(poll_id,start_at,end_at) VALUES(?,?,?)",
            [(poll_id, start, end) for start, end in parsed_slots],
        )
    flash(request, "Enquesta creada. Ja pots compartir l'enllaç.", "success")
    return go(request, "admin_poll", poll_id=str(poll_id))


@app.get("/admin/polls/{poll_id}", response_class=HTMLResponse)
def admin_poll(request: Request, poll_id: int):
    require_admin(request)
    with db() as connection:
        poll = connection.execute(
            "SELECT * FROM polls WHERE id=?", (poll_id,)
        ).fetchone()
        if not poll:
            raise HTTPException(status_code=404, detail="Enquesta no trobada")
        slots, participants, response_map, summary = load_poll_data(connection, poll_id)
        notifications = connection.execute(
            "SELECT * FROM notification_log WHERE poll_id=? ORDER BY created_at DESC LIMIT 10",
            (poll_id,),
        ).fetchall()
    public_url = str(request.url_for("public_poll", slug=poll["slug"]))
    return templates.TemplateResponse(
        "admin_poll.html",
        context(
            request,
            poll=poll,
            slots=slots,
            participants=participants,
            responses=response_map,
            summary=summary,
            notifications=notifications,
            public_url=public_url,
        ),
    )


@app.post("/admin/polls/{poll_id}/toggle")
async def admin_poll_toggle(request: Request, poll_id: int):
    require_admin(request)
    form = await request.form()
    check_csrf(request, form)
    with db() as connection:
        poll = connection.execute("SELECT status FROM polls WHERE id=?", (poll_id,)).fetchone()
        if not poll:
            raise HTTPException(status_code=404)
        new_status = "closed" if poll["status"] == "open" else "open"
        connection.execute("UPDATE polls SET status=? WHERE id=?", (new_status, poll_id))
    flash(request, "Estat de l'enquesta actualitzat.", "success")
    return go(request, "admin_poll", poll_id=str(poll_id))


@app.post("/admin/polls/{poll_id}/delete")
async def admin_poll_delete(request: Request, poll_id: int):
    require_admin(request)
    form = await request.form()
    check_csrf(request, form)
    if form.get("confirmation") != "delete":
        raise HTTPException(status_code=400, detail="Confirmació no vàlida")
    with db() as connection:
        poll = connection.execute(
            "SELECT title,status FROM polls WHERE id=?", (poll_id,)
        ).fetchone()
        if not poll:
            raise HTTPException(status_code=404, detail="Enquesta no trobada")
        if poll["status"] != "closed":
            flash(request, "Només es poden eliminar les enquestes tancades.", "error")
            return go(request, "admin_poll", poll_id=str(poll_id))
        connection.execute("DELETE FROM polls WHERE id=?", (poll_id,))
    flash(request, f"S'ha eliminat definitivament l'enquesta «{poll['title']}».", "success")
    return go(request, "admin_dashboard")


@app.get("/admin/polls/{poll_id}/export.xlsx")
def export_poll(request: Request, poll_id: int):
    require_admin(request)
    with db() as connection:
        poll = connection.execute("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()
        if not poll:
            raise HTTPException(status_code=404)
        slots, participants, response_map, summary = load_poll_data(connection, poll_id)

    workbook = Workbook()
    matrix = workbook.active
    matrix.title = "Disponibilitats"
    headers = ["Nom", "Correu"] + [fmt_dt(slot["start_at"]) for slot in slots]
    matrix.append(headers)
    for participant in participants:
        matrix.append(
            [participant["name"], participant["email"]]
            + [response_map.get((participant["id"], slot["id"]), "no") for slot in slots]
        )
    summary_sheet = workbook.create_sheet("Resum")
    summary_sheet.append(["Opció", "Sí", "Potser", "No", "Puntuació"])
    by_slot = {row["slot_id"]: row for row in summary}
    for slot in slots:
        item = by_slot[slot["id"]]
        summary_sheet.append(
            [
                fmt_dt(slot["start_at"]),
                item["yes_count"],
                item["maybe_count"],
                item["no_count"],
                item["yes_count"] * 2 + item["maybe_count"],
            ]
        )
    green = PatternFill("solid", fgColor="009639")
    for sheet in workbook.worksheets:
        for cell in sheet[1]:
            cell.fill = green
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(wrap_text=True)
        sheet.freeze_panes = "C2" if sheet.title == "Disponibilitats" else "A2"
        for column in sheet.columns:
            max_len = min(max(len(str(cell.value or "")) for cell in column) + 2, 38)
            sheet.column_dimensions[column[0].column_letter].width = max_len
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", poll["title"]).strip("_") or "enquesta"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.xlsx"'},
    )


@app.get("/p/{slug}", response_class=HTMLResponse)
def public_poll(request: Request, slug: str):
    with db() as connection:
        poll = load_poll(connection, slug)
        if not poll:
            raise HTTPException(status_code=404, detail="Enquesta no trobada")
        slots, participants, response_map, summary = load_poll_data(connection, poll["id"])
    expired = bool(poll["deadline_at"] and datetime.fromisoformat(poll["deadline_at"]) < datetime.now(UTC))
    return templates.TemplateResponse(
        "public_poll.html",
        context(
            request,
            poll=poll,
            slots=slots,
            participants=participants,
            responses=response_map,
            summary=summary,
            accepting=poll["status"] == "open" and not expired,
        ),
    )


@app.post("/p/{slug}")
async def public_poll_submit(request: Request, slug: str):
    form = await request.form()
    check_csrf(request, form)
    if str(form.get("website", "")):
        return go(request, "public_poll", slug=slug)
    name = str(form.get("name", "")).strip()
    email = str(form.get("email", "")).strip().lower()
    if len(name) < 2 or not EMAIL_RE.match(email):
        flash(request, "Indica un nom i un correu electrònic vàlids.", "error")
        return go(request, "public_poll", slug=slug)
    if form.get("privacy") != "accepted":
        flash(request, "Cal acceptar l'avís de privacitat per enviar la resposta.", "error")
        return go(request, "public_poll", slug=slug)

    with db() as connection:
        poll = load_poll(connection, slug)
        if not poll:
            raise HTTPException(status_code=404)
        expired = bool(poll["deadline_at"] and datetime.fromisoformat(poll["deadline_at"]) < datetime.now(UTC))
        if poll["status"] != "open" or expired:
            flash(request, "Aquesta enquesta ja no accepta respostes.", "error")
            return go(request, "public_poll", slug=slug)
        slots = connection.execute(
            "SELECT id,start_at,end_at FROM slots WHERE poll_id=? ORDER BY start_at", (poll["id"],)
        ).fetchall()
        now = utcnow()
        participant = connection.execute(
            "SELECT id FROM participants WHERE poll_id=? AND email=?", (poll["id"], email)
        ).fetchone()
        if participant:
            participant_id = participant["id"]
            connection.execute(
                "UPDATE participants SET name=?, updated_at=? WHERE id=?",
                (name[:120], now, participant_id),
            )
            connection.execute("DELETE FROM responses WHERE participant_id=?", (participant_id,))
        else:
            cursor = connection.execute(
                "INSERT INTO participants(poll_id,name,email,created_at,updated_at) VALUES(?,?,?,?,?)",
                (poll["id"], name[:120], email[:254], now, now),
            )
            participant_id = cursor.lastrowid
        response_rows = []
        response_lines = []
        choice_labels = {"yes": "Sí", "maybe": "Potser", "no": "No"}
        for slot in slots:
            choice = str(form.get(f"choice_{slot['id']}", "no"))
            if choice not in {"yes", "maybe", "no"}:
                choice = "no"
            response_rows.append((participant_id, slot["id"], choice))
            response_lines.append(f"- {fmt_dt(slot['start_at'])}: {choice_labels[choice]}")
        connection.executemany(
            "INSERT INTO responses(participant_id,slot_id,choice) VALUES(?,?,?)", response_rows
        )
        admins = connection.execute("SELECT email FROM admins WHERE active=1").fetchall()

    admin_url = str(request.url_for("admin_poll", poll_id=str(poll["id"])))
    with db() as connection:
        for admin in admins:
            status, detail = send_response_notification(
                recipient=admin["email"],
                poll_title=poll["title"],
                participant_name=name,
                admin_url=admin_url,
                response_details="\n".join(response_lines),
            )
            connection.execute(
                """INSERT INTO notification_log(poll_id,participant_id,recipient,status,detail,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (poll["id"], participant_id, admin["email"], status, detail, utcnow()),
            )
    flash(request, "Resposta desada. Gràcies!", "success")
    return go(request, "public_poll", slug=slug)


@app.get("/admin/admins", response_class=HTMLResponse)
def admins_page(request: Request):
    require_admin(request)
    with db() as connection:
        admins = connection.execute(
            "SELECT id,email,display_name,active,created_at FROM admins ORDER BY created_at"
        ).fetchall()
        invites = connection.execute(
            "SELECT email,expires_at,used_at,created_at FROM admin_invites ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    generated_invite_url = request.session.pop("new_invite_url", None)
    return templates.TemplateResponse(
        "admins.html",
        context(request, admins=admins, invites=invites, generated_invite_url=generated_invite_url),
    )


@app.post("/admin/admins/invite")
async def create_invite(request: Request):
    admin = require_admin(request)
    form = await request.form()
    check_csrf(request, form)
    email = str(form.get("email", "")).strip().lower()
    if not EMAIL_RE.match(email):
        flash(request, "Correu electrònic no vàlid.", "error")
        return go(request, "admins_page")
    token = random_token(32)
    expires = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0).isoformat()
    with db() as connection:
        if connection.execute("SELECT 1 FROM admins WHERE email=?", (email,)).fetchone():
            flash(request, "Aquest correu ja és administrador.", "error")
            return go(request, "admins_page")
        connection.execute(
            """INSERT INTO admin_invites(token_hash,email,created_by,expires_at,created_at)
               VALUES(?,?,?,?,?)""",
            (token_hash(token), email, admin["id"], expires, utcnow()),
        )
    invite_url = str(request.url_for("accept_invite_form", token=token))
    request.session["new_invite_url"] = invite_url
    flash(request, "Invitació creada. Copia l'enllaç i envia'l de manera segura.", "success")
    return go(request, "admins_page")


@app.get("/admin/invite/{token}", response_class=HTMLResponse)
def accept_invite_form(request: Request, token: str):
    with db() as connection:
        invite = connection.execute(
            "SELECT * FROM admin_invites WHERE token_hash=?", (token_hash(token),)
        ).fetchone()
    valid = bool(
        invite
        and not invite["used_at"]
        and datetime.fromisoformat(invite["expires_at"]) > datetime.now(UTC)
    )
    return templates.TemplateResponse(
        "accept_invite.html", context(request, invite=invite, token=token, valid=valid)
    )


@app.post("/admin/invite/{token}")
async def accept_invite_submit(request: Request, token: str):
    form = await request.form()
    check_csrf(request, form)
    name = str(form.get("name", "")).strip()
    password = str(form.get("password", ""))
    with db() as connection:
        invite = connection.execute(
            "SELECT * FROM admin_invites WHERE token_hash=?", (token_hash(token),)
        ).fetchone()
        if not invite or invite["used_at"] or datetime.fromisoformat(invite["expires_at"]) <= datetime.now(UTC):
            flash(request, "La invitació no és vàlida o ha caducat.", "error")
            return go(request, "accept_invite_form", token=token)
        if len(name) < 2 or len(password) < 12:
            flash(request, "Indica el nom i una contrasenya d'almenys 12 caràcters.", "error")
            return go(request, "accept_invite_form", token=token)
        cursor = connection.execute(
            "INSERT INTO admins(email,display_name,password_hash,created_at) VALUES(?,?,?,?)",
            (invite["email"], name[:100], hash_password(password), utcnow()),
        )
        connection.execute("UPDATE admin_invites SET used_at=? WHERE id=?", (utcnow(), invite["id"]))
        request.session["admin_id"] = cursor.lastrowid
    flash(request, "Compte administrador activat.", "success")
    return go(request, "admin_dashboard")
