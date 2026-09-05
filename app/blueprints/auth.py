"""/auth — 아이디/비밀번호 로그인 전용. 회원가입 없음(관리자가 계정 발급)."""
from functools import wraps

from werkzeug.security import check_password_hash

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, session,
                   url_for)

from ..models import admin_log, user as user_model

bp = Blueprint("auth", __name__, url_prefix="/auth")


# ---- helpers used app-wide -------------------------------------------------
def load_current_user():
    """before_request: g.user = users row or None."""
    g.user = None
    uid = session.get("uid")
    if uid:
        u = user_model.get_by_id(uid)
        if u and u["status"] == "active":
            g.user = u
        else:
            session.pop("uid", None)


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not g.get("user"):
            flash("로그인이 필요합니다.")
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not g.get("user") or g.user["role"] != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


def _login(user, next_url=None):
    session.clear()
    session["uid"] = user["id"]
    session.permanent = True
    user_model.touch_login(user["id"])
    admin_log.log(user["id"], "login", "user", user["id"], f"{user['username']} 로그인")
    return redirect(next_url if next_url and next_url.startswith("/") else "/")


# ---- login / logout --------------------------------------------------------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(request.args.get("next") or "/")
    next_url = request.values.get("next") or ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = user_model.get_by_username(username) if username else None
        if not user or not check_password_hash(user["password_hash"], password):
            flash("아이디 또는 비밀번호가 올바르지 않습니다.")
            return redirect(url_for("auth.login", next=next_url or None))
        if user["status"] != "active":
            flash("이용이 제한된 계정입니다. 관리자에게 문의해주세요.")
            return redirect(url_for("auth.login"))
        return _login(user, next_url or "/")
    return render_template("auth/login.html", next_url=next_url,
                           dev_mode=current_app.debug and current_app.config["DEV_LOGIN"])


# ---- dev login (DEBUG only) -------------------------------------------------
@bp.route("/dev-login")
def dev_login():
    """?as=user|admin — 개발용. DEV_LOGIN=1 + FLASK_DEBUG 에서만."""
    if not (current_app.debug and current_app.config["DEV_LOGIN"]):
        abort(404)
    row = user_model.get_by_username("admin" if request.args.get("as") == "admin" else "demo")
    if not row:
        abort(404, "seed data missing — run scripts/seed.py")
    return _login(row, request.args.get("next"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
