"""인앱 알림 목록 (community.py 에서 분리 — bbe_shop 은 커뮤니티 없이 알림만 쓴다)."""
from flask import Blueprint, current_app, g, render_template, request

from ..services import notify_service
from .auth import login_required

notif_bp = Blueprint("notifications", __name__)


def _page():
    return max(1, request.args.get("page", 1, type=int)), current_app.config["PER_PAGE"]


def _rel(dt):
    from datetime import datetime
    s = int((datetime.now() - dt).total_seconds())
    if s < 3600:
        return f"{max(1, s // 60)}분 전"
    if s < 86400:
        return f"{s // 3600}시간 전"
    d = s // 86400
    return "어제" if d == 1 else (f"{d}일 전" if d < 7 else dt.strftime("%m.%d"))


@notif_bp.route("/notifications")
@login_required
def notifications():
    page, per_page = _page()
    rows, total = notify_service.list_user(g.user["id"], page, per_page)
    notify_service.mark_all_read(g.user["id"])
    for r in rows:
        r["rel"] = _rel(r["created_at"])
    return render_template("community/notifications.html", rows=rows, page=page,
                           total_pages=max(1, -(-total // per_page)))
