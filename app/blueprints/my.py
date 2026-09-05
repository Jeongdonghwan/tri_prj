"""/my — 내 정보(비밀번호 변경) + 캠페인 요약."""
from werkzeug.security import check_password_hash, generate_password_hash

from flask import Blueprint, flash, g, redirect, render_template, url_for, request

from ..constants import STATUS_CLASS, STATUS_LABEL
from ..models import campaign as campaign_model
from ..models import user as user_model
from .auth import login_required

bp = Blueprint("my", __name__)


@bp.route("/my")
@login_required
def index():
    uid = g.user["id"]
    return render_template(
        "my/index.html",
        counts=campaign_model.status_counts(uid, "store"),
        done_count=campaign_model.count_done(uid),
        recent=campaign_model.list_recent_channel(uid, "store", 5),
        status_label=STATUS_LABEL, status_class=STATUS_CLASS,
    )


@bp.route("/my/password", methods=["POST"])
@login_required
def password():
    f = request.form
    if not check_password_hash(g.user["password_hash"], f.get("current") or ""):
        flash("현재 비밀번호가 올바르지 않습니다.")
    elif len(f.get("password") or "") < 8:
        flash("새 비밀번호는 8자 이상이어야 합니다.")
    elif f.get("password") != f.get("password2"):
        flash("새 비밀번호 확인이 일치하지 않습니다.")
    else:
        user_model.set_password(g.user["id"], generate_password_hash(f["password"]))
        flash("비밀번호가 변경되었습니다.")
    return redirect(url_for("my.index"))


@bp.route("/settings")
@login_required
def settings():
    return redirect(url_for("my.index"))
