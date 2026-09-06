"""Flask application factory, sidebar MENU constant, context processors."""
from datetime import date, datetime

from flask import Flask, g, request

from .config import Config

# Sidebar menu. Keep in sync with sidebar.html / bottom_tab.html whenever a route is added.
# item = {label, icon (lucide name), href, external?, children?: [{label, href}], key?}
MENU = {
    "user": [
        {
            "title": "기본",
            "items": [
                {"label": "공지사항", "icon": "megaphone", "href": "/notice"},
            ],
        },
        {
            "title": "유입관리",
            "items": [
                {"label": "캠페인 관리", "icon": "shopping-bag", "href": "/campaign/store"},
                {"label": "로그 기록", "icon": "scroll-text", "href": "/logs"},
            ],
        },
    ],
    "admin": [
        {
            "title": "운영",
            "items": [
                {"label": "운영 현황", "icon": "trending-up", "href": "/admin"},
                {"label": "변경 이력", "icon": "clipboard-list", "href": "/admin/changes"},
                {"label": "주문 관리", "icon": "map-pin", "href": "/admin/orders"},
            ],
        },
        {
            "title": "설정",
            "items": [
                {"label": "공지사항", "icon": "pen-line", "href": "/admin/content"},
                {"label": "계정 관리", "icon": "users", "href": "/admin/users"},
                {"label": "로그 기록", "icon": "scroll-text", "href": "/admin/logs"},
            ],
        },
    ],
}

# Routes that are not in the sidebar but still need a breadcrumb label.
EXTRA_CRUMBS = {
    "/": (None, "대시보드"),
    "/my": (None, "마이페이지"),
    "/settings": (None, "설정"),
    "/auth/login": (None, "로그인"),
    "/auth/logout": (None, "로그아웃"),
    "/notifications": (None, "알림"),
}


def _flatten_menu():
    """Return list of (href, parent_label, label) for every internal link."""
    out = []
    for mode in ("user", "admin"):
        for sec in MENU[mode]:
            for item in sec["items"]:
                if item.get("external"):
                    continue
                if "children" in item:
                    for ch in item["children"]:
                        out.append((ch["href"], item["label"], ch["label"]))
                else:
                    parent = "관리자" if mode == "admin" else sec["title"]
                    out.append((item["href"], parent, item["label"]))
    for href, (parent, label) in EXTRA_CRUMBS.items():
        out.append((href, parent, label))
    return out


_LINKS = _flatten_menu()


def resolve_active(path):
    """Longest-prefix match."""
    best = None
    for href, parent, label in _LINKS:
        if path == href or (href != "/" and path.startswith(href + "/")):
            if best is None or len(href) > len(best[0]):
                best = (href, parent, label)
    return best


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    from . import db
    from .services import notify_service
    db.init_app(app)

    from .blueprints import main, auth, notice, campaign, my, admin, rank_api, notifications
    for bp in (main.bp, auth.bp, notice.bp, campaign.bp, my.bp, admin.bp,
               rank_api.bp, notifications.notif_bp):
        app.register_blueprint(bp)

    app.before_request(auth.load_current_user)

    # 전체 화면 로그인 강제: 로그인 관련 경로·정적 파일·순위 콜백만 예외 (내부용 사이트)
    _PUBLIC_PREFIXES = ("/auth/", "/static/", "/api/rank/callback", "/favicon")

    @app.before_request
    def _force_login():
        from flask import redirect, url_for
        if g.get("user") or request.path.startswith(_PUBLIC_PREFIXES):
            return None
        if request.path.startswith("/api/"):
            from flask import jsonify
            return jsonify({"ok": False, "message": "로그인이 필요합니다."}), 401
        return redirect(url_for("auth.login", next=request.path if request.path != "/" else None))

    @app.context_processor
    def inject_layout():
        path = request.path
        is_admin_path = path == "/admin" or path.startswith("/admin/")
        active = resolve_active(path)
        user = g.get("user")
        try:
            from .models import settings as settings_model
            sv = settings_model.get_all()
        except Exception:
            sv = {}
        strip = {"on": sv.get("strip_on") == "1", "text": sv.get("strip_text") or "",
                 "link": sv.get("strip_link") or "", "bg": sv.get("strip_bg") or "#2563EB"}
        return {
            "APP_NAME": app.config["APP_NAME"], "strip": strip,
            "MENU": MENU,
            "current_user": user,
            "unread_count": notify_service.unread_count(user["id"]) if user else 0,
            "is_admin_path": is_admin_path,
            "active_href": active[0] if active else None,
            "crumb_parent": active[1] if active else None,
            "crumb_label": active[2] if active else "대시보드",
        }

    @app.template_filter("fmt_date")
    def fmt_date(v, fmt="%m.%d"):
        if not v:
            return ""
        if isinstance(v, (datetime, date)):
            return v.strftime(fmt)
        return str(v)

    @app.template_filter("won")
    def won(v):
        try:
            return f"{int(v):,}원"
        except (TypeError, ValueError):
            return v

    @app.template_filter("fmt_num")
    def fmt_num(v):
        try:
            return f"{int(v):,}"
        except (TypeError, ValueError):
            return v

    return app
