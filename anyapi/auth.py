"""Supabase Auth integration with server-side sessions stored in a signed HttpOnly cookie."""

from __future__ import annotations

import re
import secrets
import time
from functools import wraps
from typing import Any, Callable
from urllib.parse import urlparse

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .security import pkce_pair
from .slugs import RESERVED_NAMES, normalize_username, username_error
from .supabase import Supabase, SupabaseError

bp = Blueprint("auth", __name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_REFRESH_MARGIN = 60


def sb() -> Supabase:
    return current_app.extensions["anyapi.supabase"]


def csrf_token() -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def verify_csrf() -> None:
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("csrf") or ""
    if not expected or not secrets.compare_digest(sent, expected):
        abort(400, description="Invalid or missing CSRF token. Reload the page and try again.")


def _store_session(data: dict[str, Any]) -> None:
    user = data.get("user") or {}
    session["auth"] = {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": int(data.get("expires_at") or time.time() + int(data.get("expires_in", 3600))),
        "user_id": user.get("id"),
        "email": user.get("email"),
    }
    session.permanent = True


def clear_session() -> None:
    session.pop("auth", None)
    session.pop("profile", None)


def _load_auth() -> dict[str, Any] | None:
    auth = session.get("auth")
    if not auth:
        return None
    if auth.get("expires_at", 0) - _REFRESH_MARGIN < time.time():
        try:
            _store_session(sb().refresh(auth["refresh_token"]))
            auth = session["auth"]
        except SupabaseError:
            clear_session()
            return None
    return auth


def current_user() -> dict[str, Any] | None:
    """Return {id, email, access_token, username} for the signed-in user, or None."""
    if "anyapi_user" in g:
        return g.anyapi_user
    auth = _load_auth()
    user = None
    if auth:
        profile = session.get("profile")
        if not profile or profile.get("id") != auth["user_id"]:
            try:
                profile = sb().user(auth["access_token"]).select_one(
                    "profiles", {"id": f"eq.{auth['user_id']}", "select": "id,username,display_name"}
                )
            except SupabaseError:
                profile = None
            if profile:
                session["profile"] = profile
        if profile:
            user = {
                "id": auth["user_id"],
                "email": auth.get("email"),
                "access_token": auth["access_token"],
                "username": profile["username"],
                "display_name": profile.get("display_name"),
            }
    g.anyapi_user = user
    return user


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        if current_user() is None:
            if request.path.startswith("/_api/"):
                return jsonify({"error": {"type": "unauthorized", "message": "Sign in required"}}), 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapper


def _safe_next(target: str | None) -> str:
    if not target:
        return url_for("pages.dashboard")
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return url_for("pages.dashboard")
    return target


def _callback_url() -> str:
    settings = current_app.config["ANYAPI_SETTINGS"]
    if not settings.is_production and settings.dev_redirect_url:
        return settings.dev_redirect_url
    base = settings.public_base_url or request.url_root.rstrip("/")
    return f"{base}/auth/callback"


def _friendly_auth_error(exc: SupabaseError, fallback: str) -> str:
    code = (exc.code or "").lower()
    message = exc.message.lower()
    if exc.status == 429 or "rate" in code:
        return "Too many attempts. Please wait a minute and try again."
    if "email_not_confirmed" in code or "not confirmed" in message:
        return "Please confirm your email address first. Check your inbox for the confirmation link."
    if "weak_password" in code or "password should" in message:
        return exc.message
    if "email_address_invalid" in code:
        return "That email address cannot be used. Try another one."
    current_app.logger.warning("auth error %s %s %s", exc.status, exc.code, exc.message)
    return fallback


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET" and current_user():
        return redirect(url_for("pages.dashboard"))
    if request.method == "POST":
        verify_csrf()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not _EMAIL.match(email) or not password:
            flash("Enter a valid email and password.", "error")
        else:
            try:
                _store_session(sb().sign_in_password(email, password))
                session.pop("profile", None)
                return redirect(_safe_next(request.args.get("next")))
            except SupabaseError as exc:
                if exc.status in (400, 401) and "not confirmed" not in exc.message.lower():
                    flash("Invalid email or password.", "error")
                else:
                    flash(_friendly_auth_error(exc, "Sign in failed unexpectedly. Please try again."), "error")
    return render_template("auth/login.html", next=request.args.get("next", ""))


@bp.get("/_api/username-available")
def username_available():
    raw = request.args.get("username", "")
    username = normalize_username(raw)
    error = username_error(username)
    if error:
        return jsonify({"available": False, "reason": error})
    try:
        available = bool(sb().anon().rpc("username_available", {"p_username": username}))
    except SupabaseError:
        return jsonify({"available": False, "reason": "Could not check availability right now."}), 503
    return jsonify({"available": available, "reason": None if available else "That username is taken."})


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET" and current_user():
        return redirect(url_for("pages.dashboard"))
    form = {"email": "", "username": "", "display_name": ""}
    if request.method == "POST":
        verify_csrf()
        form = {
            "email": request.form.get("email", "").strip().lower(),
            "username": normalize_username(request.form.get("username", "")),
            "display_name": request.form.get("display_name", "").strip()[:80],
        }
        password = request.form.get("password", "")
        error = None
        if not _EMAIL.match(form["email"]):
            error = "Enter a valid email address."
        elif username_error(form["username"]):
            error = username_error(form["username"])
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        if not error:
            try:
                if not sb().anon().rpc("username_available", {"p_username": form["username"]}):
                    error = "That username is taken."
            except SupabaseError:
                error = "Could not verify the username right now. Please try again."
        if not error:
            verifier, challenge = pkce_pair()
            try:
                data = sb().sign_up(
                    form["email"],
                    password,
                    {"username": form["username"], "display_name": form["display_name"]},
                    _callback_url(),
                    challenge,
                )
                session["pkce_verifier"] = verifier
                if data.get("access_token"):
                    _store_session(data)
                    return redirect(url_for("pages.dashboard"))
                return redirect(url_for("auth.signup_success", email=form["email"]))
            except SupabaseError as exc:
                if "already registered" in exc.message.lower() or exc.code == "user_already_exists":
                    # Same response as success to avoid account enumeration.
                    return redirect(url_for("auth.signup_success", email=form["email"]))
                if "database error" in exc.message.lower():
                    error = "That username is no longer available. Choose another."
                else:
                    error = _friendly_auth_error(exc, "Sign up failed unexpectedly. Please try again.")
        flash(error, "error")
    return render_template("auth/signup.html", form=form, reserved=sorted(RESERVED_NAMES))


@bp.get("/signup/success")
def signup_success():
    return render_template("auth/signup_success.html", email=request.args.get("email", ""))


@bp.get("/auth/callback")
def callback():
    code = request.args.get("code")
    next_url = _safe_next(request.args.get("next"))
    if request.args.get("error"):
        flash(request.args.get("error_description") or "The link is invalid or has expired.", "error")
        return redirect(url_for("auth.login"))
    if code:
        verifier = session.pop("pkce_verifier", None)
        if not verifier:
            flash("Email confirmed. Sign in to continue.", "success")
            return redirect(url_for("auth.login"))
        try:
            _store_session(sb().exchange_code(code, verifier))
            session.pop("profile", None)
        except SupabaseError:
            flash("This link is invalid or has expired. Sign in or request a new link.", "error")
            return redirect(url_for("auth.login"))
        if session.pop("recovery_pending", False):
            return redirect(url_for("auth.reset_password"))
        return redirect(next_url)
    # Implicit-flow links put tokens in the URL fragment; a tiny page posts them back.
    return render_template("auth/callback.html")


@bp.post("/auth/session")
def accept_fragment_session():
    verify_csrf()
    payload = request.get_json(silent=True) or {}
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not access_token or not refresh_token:
        return jsonify({"ok": False}), 400
    try:
        user = sb().get_user(access_token)
    except SupabaseError:
        return jsonify({"ok": False}), 401
    _store_session(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": int(payload.get("expires_in") or 3600),
            "user": user,
        }
    )
    session.pop("profile", None)
    target = url_for("auth.reset_password") if payload.get("type") == "recovery" else url_for("pages.dashboard")
    return jsonify({"ok": True, "redirect": target})


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    sent = False
    if request.method == "POST":
        verify_csrf()
        email = request.form.get("email", "").strip().lower()
        if _EMAIL.match(email):
            verifier, challenge = pkce_pair()
            try:
                sb().recover(email, _callback_url(), challenge)
                session["pkce_verifier"] = verifier
                session["recovery_pending"] = True
            except SupabaseError as exc:
                if exc.status == 429:
                    flash("Too many requests. Please wait a minute and try again.", "error")
                    return render_template("auth/forgot.html", sent=False)
        sent = True
    return render_template("auth/forgot.html", sent=sent)


@bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    user = current_user()
    auth = session.get("auth")
    if not auth:
        flash("Open the reset link from your email to choose a new password.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        verify_csrf()
        password = request.form.get("password", "")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != request.form.get("confirm", ""):
            flash("Passwords do not match.", "error")
        else:
            try:
                sb().update_password(auth["access_token"], password)
                flash("Password updated.", "success")
                return redirect(url_for("pages.dashboard"))
            except SupabaseError as exc:
                flash(_friendly_auth_error(exc, "Could not update the password. Try again."), "error")
    return render_template("auth/reset.html", user=user)


@bp.post("/logout")
def logout():
    verify_csrf()
    auth = session.get("auth")
    if auth:
        sb().sign_out(auth["access_token"])
    clear_session()
    return redirect(url_for("pages.landing"))


__all__ = ["bp", "current_user", "login_required", "csrf_token", "verify_csrf", "sb", "RESERVED_NAMES"]
