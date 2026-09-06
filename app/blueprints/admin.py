"""/admin/* — operator screens. Every write is recorded in admin_log."""
import io
import re
from datetime import date, datetime

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, send_file,
                   url_for)

from ..constants import (CHANNEL_LABEL, STATUS_CLASS, STATUS_LABEL,
                         STATUS_ORDER)
from ..models import admin_log
from ..models import campaign as campaign_model
from ..models import content as content_model
from ..models import media as media_model
from ..models import settings as settings_model
from ..models import user as user_model
from ..services import campaign_service, content_service, forbidden_service, media_service
from .auth import admin_required
from .main import render_placeholder

bp = Blueprint("admin", __name__, url_prefix="/admin")

PAGES = {
    "": "운영 현황", "orders": "주문 관리", "media": "매체사 관리", "content": "공지사항", "users": "계정 관리",
    "logs": "로그 기록",
}


def _log(action, target_type=None, target_id=None, summary=None):
    admin_log.log(g.user["id"], action, target_type, target_id, summary)


def _back(default):
    ref = request.form.get("back") or request.referrer
    return redirect(ref if ref and "/admin" in ref else default)


def _page():
    return max(1, request.args.get("page", 1, type=int)), current_app.config["PER_PAGE"]


# =============================================================== dashboard
@bp.route("")
@admin_required
def index():
    counts = campaign_model.admin_status_counts()
    return render_template(
        "admin/dashboard.html",
        no_rank=campaign_model.running_without_today_rank(), running=counts.get("running", 0),
        pending=counts.get("pending", 0), today_n=campaign_model.today_intake()["n"],
        by_media=campaign_model.today_intake_by_media(5), logs=admin_log.recent(10),
        channel_label=CHANNEL_LABEL,
    )


# =============================================================== orders
@bp.route("/orders")
@admin_required
def orders():
    status = request.args.get("status") or None
    if status not in STATUS_LABEL:
        status = None
    channel = request.args.get("channel") or None
    if channel not in CHANNEL_LABEL:
        channel = None
    media_id = request.args.get("media", type=int)
    period = request.args.get("period") or None
    q = (request.args.get("q") or "").strip()[:60] or None
    page, per_page = _page()
    rows = campaign_model.admin_list(status, channel, media_id, period, q, page, per_page)
    for r in rows:
        r["warn"] = forbidden_service.check([r["product_name"], r["main_keyword"]], r["channel"])
        r["day_idx"] = campaign_service.day_index(r)
        r["total_days"] = campaign_service.days_between(r["start_date"], r["end_date"])
        r["today"] = campaign_model.today_rank(r["id"]) if r["status"] == "running" else None
    total = campaign_model.admin_count(status, channel, media_id, period, q)
    counts = campaign_model.admin_status_counts()
    medias = media_model.list_by_channel("store", False)
    return render_template(
        "admin/orders.html", rows=rows, page=page, total_pages=max(1, -(-total // per_page)), counts=counts,
        total_all=sum(counts.values()), status=status, channel=channel, media_id=media_id, period=period, q=q, medias=medias,
        status_order=STATUS_ORDER, status_label=STATUS_LABEL, status_class=STATUS_CLASS, channel_label=CHANNEL_LABEL,
    )


def _apply_action(c, action, reason=""):
    """단건/드롭다운 공용. (ok, message) 반환."""
    label = f"{c['user_username'] if c.get('user_username') else ''} 슬롯{c['slot_no']}"
    try:
        if action == "stop":
            c = campaign_service.stop(c, g.user["id"], "운영팀 중단")
            _log("order_stop", "campaign", c["id"], f"{label} 중단")
        elif action == "done":
            c = campaign_service.transition(c, "done", g.user["id"], f"구동 완료 · 누적 {campaign_model.total_done_qty(c['id']):,}건")
            _log("order_done", "campaign", c["id"], f"{label} 완료")
        else:
            return False, "알 수 없는 작업"
        return True, f"{label} → {STATUS_LABEL[c['status']]}"
    except campaign_service.CampaignError as e:
        return False, f"{label}: {e}"


@bp.route("/orders/<int:campaign_id>/action", methods=["POST"])
@admin_required
def order_action(campaign_id):
    c = campaign_model.get(campaign_id) or abort(404)
    action = request.form.get("action", "")
    if action == "memo":
        campaign_model.set_admin_memo(c["id"], (request.form.get("memo") or "").strip()[:1000])
        _log("order_memo", "campaign", c["id"], f"슬롯{c['slot_no']} 메모 수정")
        flash("메모를 저장했습니다.")
    elif action == "status":
        target = request.form.get("status")
        mapping = {"stopped": "stop", "done": "done"}
        ok, msg = _apply_action(c, mapping.get(target, ""), request.form.get("reason", ""))
        flash(msg)
    else:
        ok, msg = _apply_action(c, action, request.form.get("reason", ""))
        flash(msg)
    return _back(url_for("admin.orders"))


@bp.route("/orders/<int:campaign_id>/rank", methods=["POST"])
@admin_required
def order_rank(campaign_id):
    c = campaign_model.get(campaign_id) or abort(404)
    try:
        day = date.fromisoformat(request.form.get("date") or date.today().isoformat())
        rank = int(request.form.get("rank"))
        done_qty = int(request.form.get("done_qty") or c["daily_qty"])
        c = campaign_service.record_rank(c, day, rank, done_qty, g.user["id"])
        _log("order_rank", "campaign", c["id"], f"슬롯{c['slot_no']} 순위 입력 {day:%m.%d} {c['rank_start']}→{rank} · {done_qty}건")
        flash(f"순위 저장: {rank}위")
    except (ValueError, TypeError):
        flash("순위/수량을 숫자로 입력해주세요.")
    except campaign_service.CampaignError as e:
        flash(str(e))
    return _back(url_for("admin.orders"))


@bp.route("/orders/<int:campaign_id>/terms", methods=["POST"])
@admin_required
def order_terms(campaign_id):
    c = campaign_model.get(campaign_id) or abort(404)
    try:
        s_ = date.fromisoformat(request.form.get("start_date", ""))
        e_ = date.fromisoformat(request.form.get("end_date", ""))
        dq = int(request.form.get("daily_qty", "0"))
        c = campaign_service.update_terms(c, g.user["id"], s_, e_, dq)
        _log("order_terms", "campaign", c["id"], f"슬롯{c['slot_no']} 기간·수량 변경 {s_}~{e_} · 일 {dq}건")
        flash("기간·수량을 변경했습니다.")
    except ValueError:
        flash("기간/수량 형식을 확인해주세요.")
    except campaign_service.CampaignError as e:
        flash(str(e))
    return _back(url_for("admin.orders"))


@bp.route("/orders/export")
@admin_required
def orders_export():
    from openpyxl import Workbook
    status = request.args.get("status") or None
    channel = request.args.get("channel") or None
    rows = campaign_model.admin_all(status if status in STATUS_LABEL else None, channel if channel in CHANNEL_LABEL else None,
                                    request.args.get("media", type=int), request.args.get("period") or None, request.args.get("q") or None)
    wb = Workbook(); ws = wb.active; ws.title = "orders"
    ws.append(["아이디", "슬롯번호", "상태", "상품", "키워드", "매체", "시작", "종료", "일 수량", "총 수량",
               "시작 순위", "현재 순위", "링크", "등록일"])
    for r in rows:
        ws.append([r["user_username"], r["slot_no"], STATUS_LABEL[r["status"]], r["product_name"], r["main_keyword"],
                   r["media_name"], r["start_date"], r["end_date"], r["daily_qty"], r["total_qty"],
                   r["rank_start"], r["rank_now"], r["target_url"], r["created_at"]])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    _log("order_export", None, None, f"엑셀 내보내기 {len(rows)}건")
    return send_file(buf, as_attachment=True, download_name=f"orders_{date.today():%Y%m%d}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# =============================================================== media
@bp.route("/media")
@admin_required
def media():
    channel = request.args.get("channel", "place")
    if channel not in CHANNEL_LABEL:
        channel = "place"
    rows = media_model.list_by_channel(channel, False)
    month = media_model.month_intake_counts()
    for m in rows:
        m["eff"] = media_model.efficiency(m)
        m["auto"] = media_service.calc_efficiency(m["id"])
        m["month"] = month.get(m["id"], 0)
    counts = {ch: len(media_model.list_by_channel(ch, False)) for ch in CHANNEL_LABEL}
    edit_id = request.args.get("edit", type=int)
    edit = media_model.get(edit_id) if edit_id else None
    if edit:
        edit["auto"] = media_service.calc_efficiency(edit["id"])
    new = request.args.get("new") == "1"
    return render_template("admin/media.html", channel=channel, rows=rows, counts=counts, edit=edit, new=new,
                           channel_label=CHANNEL_LABEL)


@bp.route("/media/save", methods=["POST"])
@admin_required
def media_save():
    f = request.form
    mid = f.get("id", type=int)
    channel = f.get("channel") if f.get("channel") in CHANNEL_LABEL else "place"
    try:
        fields = {
            "channel": channel, "name": f.get("name", "").strip()[:40],
            "group_name": f.get("group_name") if f.get("group_name") in ("리워드", "유입", "복합") else "유입",
            "tagline": f.get("tagline", "").strip()[:80] or None, "color": f.get("color", "#4B5563")[:7],
            "unit_price": int(f.get("unit_price")), "list_price": int(f["list_price"]) if f.get("list_price", "").strip() else None,
            "min_days": int(f.get("min_days", 3)), "min_daily": int(f.get("min_daily", 50)), "max_daily": int(f.get("max_daily", 500)),
            "cutoff_time": (f.get("cutoff_time") or "13:30")[:5] + ":00",
            "efficiency_manual": int(f["efficiency_manual"]) if f.get("efficiency_manual", "").strip() else None,
            "badge": f.get("badge") if f.get("badge") in ("rec", "best", "new") else None,
            "eff_level": f.get("eff_level") if f.get("eff_level") in ("normal", "good", "best") else "good",
            "eff_note": f.get("eff_note", "").strip()[:120] or None,
            "description": f.get("description", "").strip() or None,
            "is_active": 1 if f.get("is_active") == "1" else 0, "same_day": 1 if f.get("same_day") == "1" else 0,
            "sort": int(f.get("sort") or 0),
        }
        if not fields["name"]:
            raise ValueError("이름을 입력해주세요.")
        if fields["min_daily"] > fields["max_daily"]:
            raise ValueError("일 수량 범위가 올바르지 않습니다.")
    except (ValueError, TypeError) as e:
        flash(f"입력값을 확인해주세요: {e}")
        return redirect(url_for("admin.media", channel=channel, edit=mid))
    if mid:
        media_model.update_fields(mid, fields)
        _log("media_update", "media", mid, f"{fields['name']} 수정 · 단가 {fields['unit_price']:,}")
    else:
        mid = media_model.insert(fields)
        _log("media_create", "media", mid, f"{fields['name']} 추가")
    try:
        if request.files.get("logo") and request.files["logo"].filename:
            media_service.save_logo(mid, request.files["logo"])
            _log("media_logo", "media", mid, f"{fields['name']} 로고 업로드")
    except media_service.MediaError as e:
        flash(f"저장됨. 로고 오류: {e}")
        return redirect(url_for("admin.media", channel=channel, edit=mid))
    flash(f"{fields['name']} 저장")
    return redirect(url_for("admin.media", channel=channel, edit=mid))


@bp.route("/media/<int:media_id>/toggle", methods=["POST"])
@admin_required
def media_toggle(media_id):
    m = media_model.get(media_id) or abort(404)
    media_model.update_fields(media_id, {"is_active": 0 if m["is_active"] else 1})
    _log("media_toggle", "media", media_id, f"{m['name']} 노출 {'OFF' if m['is_active'] else 'ON'}")
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, is_active=0 if m["is_active"] else 1)
    return redirect(url_for("admin.media", channel=m["channel"]))


@bp.route("/media/<int:media_id>/delete", methods=["POST"])
@admin_required
def media_delete(media_id):
    m = media_model.get(media_id) or abort(404)
    used = media_model.usage_count(media_id)
    if used:
        flash(f"'{m['name']}'는 캠페인 {used}건이 연결되어 삭제할 수 없습니다. 노출 OFF로 숨겨주세요.")
        return redirect(url_for("admin.media", channel=m["channel"], edit=media_id))
    media_service.delete_logo(media_id)
    media_model.delete(media_id)
    _log("media_delete", "media", media_id, f"{m['name']} 삭제 ({m['channel']})")
    flash(f"'{m['name']}' 매체사를 삭제했습니다.")
    return redirect(url_for("admin.media", channel=m["channel"]))


@bp.route("/media/<int:media_id>/logo/delete", methods=["POST"])
@admin_required
def media_logo_delete(media_id):
    m = media_model.get(media_id) or abort(404)
    media_service.delete_logo(media_id)
    _log("media_logo_delete", "media", media_id, f"{m['name']} 로고 삭제")
    return redirect(url_for("admin.media", channel=m["channel"], edit=media_id))


# =============================================================== content
@bp.route("/content")
@admin_required
def content():
    tab = request.args.get("tab", "all")
    if tab not in ("all", "notice", "info", "series", "draft"):
        tab = "all"
    page, per_page = _page()
    rows, total = content_model.admin_list(tab, page, per_page)
    counts = content_model.admin_counts()
    edit_id = request.args.get("edit", type=int)
    edit = content_model.get_any(edit_id) if edit_id else None
    new = request.args.get("new") == "1"
    return render_template("admin/content.html", rows=rows, tab=tab, page=page, total_pages=max(1, -(-total // per_page)), counts=counts,
                           edit=edit, new=new or edit is not None, notice_categories=content_service.NOTICE_CATEGORIES,
                           info_categories=content_service.INFO_CATEGORIES, channel_label=CHANNEL_LABEL,
                           next_series_no=content_model.next_series_no())


@bp.route("/content/save", methods=["POST"])
@admin_required
def content_save():
    f = request.form
    cid = f.get("id", type=int)
    board = f.get("board") if f.get("board") in ("notice", "info", "series") else "info"
    title = (f.get("title") or "").strip()[:200]
    if not title:
        flash("제목을 입력해주세요.")
        return redirect(url_for("admin.content", edit=cid, new=1))
    mode = f.get("mode", "publish")  # publish | draft
    publish_at = None
    status = "draft" if mode == "draft" else "published"
    if mode == "publish" and f.get("when") == "schedule" and f.get("publish_at"):
        try:
            publish_at = datetime.fromisoformat(f["publish_at"])
            status = "scheduled" if publish_at > datetime.now() else "published"
        except ValueError:
            flash("예약 일시 형식이 올바르지 않습니다.")
            return redirect(url_for("admin.content", edit=cid, new=1))
    if status == "published" and publish_at is None:
        publish_at = datetime.now()
    category = f.get("category") or None
    if board == "notice" and category not in content_service.NOTICE_CATEGORIES:
        category = "update"
    if board == "info" and category not in content_service.INFO_CATEGORIES:
        category = "guide"
    fields = {
        "board": board, "category": "series" if board == "series" else category,
        "channel": f.get("channel") if f.get("channel") in CHANNEL_LABEL else None,
        "series_no": f.get("series_no", type=int) if board == "series" else None,
        "title": title, "body": content_service.sanitize(f.get("body")), "status": status, "publish_at": publish_at,
        "is_pinned": 1 if f.get("is_pinned") == "1" else 0, "show_dashboard": 1 if f.get("show_dashboard") == "1" else 0,
        "notify": 1 if (board == "notice" and f.get("notify") == "1") else 0, "author_id": g.user["id"],
    }
    if board == "series" and not fields["series_no"]:
        fields["series_no"] = content_model.next_series_no()
    cid = content_model.save(cid, fields)
    _log("content_save", "content", cid, f"[{board}] {title} · {status}")
    flash({"draft": "임시저장했습니다.", "scheduled": "예약 발행 등록", "published": "발행했습니다."}[status])
    return redirect(url_for("admin.content", edit=cid))


@bp.route("/content/<int:content_id>/pin", methods=["POST"])
@admin_required
def content_pin(content_id):
    c = content_model.get_any(content_id) or abort(404)
    content_model.save(content_id, {"is_pinned": 0 if c["is_pinned"] else 1})
    _log("content_pin", "content", content_id, f"{c['title']} 고정 {'해제' if c['is_pinned'] else '설정'}")
    return _back(url_for("admin.content"))


@bp.route("/content/<int:content_id>/order/<direction>", methods=["POST"])
@admin_required
def content_order(content_id, direction):
    content_model.swap_series_order(content_id, "up" if direction == "up" else "down")
    _log("content_order", "content", content_id, f"시리즈 순서 {direction}")
    return redirect(url_for("admin.content", tab="series"))


@bp.route("/content/<int:content_id>/delete", methods=["POST"])
@admin_required
def content_delete(content_id):
    c = content_model.get_any(content_id) or abort(404)
    content_model.delete(content_id)
    _log("content_delete", "content", content_id, f"{c['title']} 삭제")
    flash("삭제했습니다.")
    return redirect(url_for("admin.content"))


@bp.route("/content/upload", methods=["POST"])
@admin_required
def content_upload():
    try:
        url = content_service.save_image(request.files.get("image"))
    except content_service.ContentError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, url=url)


# =============================================================== banners
@bp.route("/banners/strip", methods=["POST"])
@admin_required
def banners_strip():
    from ..models import settings as settings_model
    f = request.form
    bg = f.get("strip_bg") or "#2563EB"
    if not re.match(r"^#[0-9A-Fa-f]{6}$", bg):
        bg = "#2563EB"
    settings_model.set_many({
        "strip_text": (f.get("strip_text") or "").strip()[:120],
        "strip_link": (f.get("strip_link") or "").strip()[:300],
        "strip_bg": bg,
        "strip_on": "1" if f.get("strip_on") == "1" else "0",
    })
    _log("strip_save", "settings", 0, "띠배너 설정 저장")
    flash("띠배너 설정을 저장했습니다.")
    return redirect(url_for("admin.banners"))


# =============================================================== users (계정 발급/관리 — 회원가입 없음)
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,30}$")


@bp.route("/users")
@admin_required
def users():
    q = (request.args.get("q") or "").strip()[:40] or None
    status = request.args.get("status") or None
    page, per_page = _page()
    rows, total = user_model.list_admin(q, status if status in ("active", "suspended") else None, page, per_page)
    from datetime import timedelta
    return render_template("admin/users.html", rows=rows, q=q, status=status, page=page,
                           total_pages=max(1, -(-total // per_page)), counts=user_model.count_by_status(),
                           medias=media_model.list_by_channel("store", False),
                           issue_start=date.today(), issue_end=date.today() + timedelta(days=29))


@bp.route("/users/create", methods=["POST"])
@admin_required
def user_create():
    from werkzeug.security import generate_password_hash
    f = request.form
    username = (f.get("username") or "").strip()
    password = f.get("password") or ""
    role = f.get("role") if f.get("role") in ("admin", "user") else "user"
    if not USERNAME_RE.match(username):
        flash("아이디는 영문/숫자/-/_ 3~30자로 입력해주세요.")
    elif len(password) < 8:
        flash("비밀번호는 8자 이상이어야 합니다.")
    elif user_model.get_by_username(username):
        flash("이미 존재하는 아이디입니다.")
    else:
        uid = user_model.create(username, generate_password_hash(password), (f.get("nickname") or "").strip() or None,
                                role, (f.get("company") or "").strip()[:100], (f.get("memo") or "").strip()[:255])
        _log("user_create", "user", uid, f"계정 발급 {username} ({'관리자' if role == 'admin' else '일반'})")
        flash(f"{username} 계정을 발급했습니다.")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/update", methods=["POST"])
@admin_required
def user_update(user_id):
    from werkzeug.security import generate_password_hash
    u = user_model.get_by_id(user_id) or abort(404)
    f = request.form
    role = f.get("role") if f.get("role") in ("admin", "user") else u["role"]
    if u["id"] == g.user["id"] and role != "admin":
        flash("본인 계정의 관리자 권한은 해제할 수 없습니다.")
        return redirect(url_for("admin.users", q=request.args.get("q")))
    user_model.update_account(user_id, (f.get("nickname") or "").strip() or u["username"], role,
                              (f.get("company") or "").strip()[:100], (f.get("memo") or "").strip()[:255])
    changed = ["정보"]
    if f.get("password"):
        if len(f["password"]) < 8:
            flash("비밀번호는 8자 이상이어야 합니다. (다른 정보는 저장됨)")
        else:
            user_model.set_password(user_id, generate_password_hash(f["password"]))
            changed.append("비밀번호")
    _log("user_update", "user", user_id, f"{u['username']} 계정 수정 ({'/'.join(changed)})")
    flash(f"{u['username']} 계정을 수정했습니다.")
    return redirect(url_for("admin.users", q=request.args.get("q")))


@bp.route("/users/<int:user_id>/issue", methods=["POST"])
@admin_required
def user_issue(user_id):
    """계정에 캠페인 슬롯 발급 — 기간·일 수량·개수는 어드민이 정하고, 사용자는 내용만 등록."""
    u = user_model.get_by_id(user_id) or abort(404)
    media_ = media_model.get(request.form.get("media_id", type=int) or 0)
    if not media_ or not media_["is_active"]:
        flash("매체를 선택해주세요.")
        return redirect(url_for("admin.users"))
    try:
        s_ = date.fromisoformat(request.form.get("start_date", ""))
        e_ = date.fromisoformat(request.form.get("end_date", ""))
        dq = int(request.form.get("daily_qty", "0"))
        n = int(request.form.get("count", "1"))
        ids = campaign_service.issue(g.user["id"], u, media_, s_, e_, dq, n)
        _log("campaign_issue", "user", u["id"], f"{u['username']} 슬롯 {len(ids)}개 발급 · {s_}~{e_} · 일 {dq}건")
        flash(f"{u['username']} 계정에 캠페인 슬롯 {len(ids)}개를 발급했습니다.")
    except ValueError:
        flash("기간/수량/개수 형식을 확인해주세요.")
    except campaign_service.CampaignError as e:
        flash(str(e))
    return redirect(url_for("admin.users", q=request.args.get("q")))


@bp.route("/users/<int:user_id>/status", methods=["POST"])
@admin_required
def user_status(user_id):
    u = user_model.get_by_id(user_id) or abort(404)
    if u["id"] == g.user["id"]:
        flash("본인 계정은 정지할 수 없습니다.")
        return redirect(url_for("admin.users"))
    new = "active" if u["status"] == "suspended" else "suspended"
    user_model.set_status(user_id, new)
    _log("user_status", "user", user_id, f"{u['username']} → {'정상' if new == 'active' else '정지'}")
    flash(f"{u['username']} {'정지 해제' if new == 'active' else '정지'}")
    return redirect(url_for("admin.users", q=request.args.get("q")))


# =============================================================== logs (로그 기록)
ACTION_LABEL = {
    "login": "로그인", "user_create": "계정 발급", "user_update": "계정 수정", "user_status": "계정 상태",
    "order_start": "구동 시작", "order_stop": "캠페인 중단", "order_done": "캠페인 완료",
    "order_rank": "순위 입력", "order_terms": "기간·수량 변경", "campaign_issue": "슬롯 발급",
    "media_save": "매체 저장", "media_toggle": "매체 토글", "media_delete": "매체 삭제",
    "content_save": "공지 저장", "content_delete": "공지 삭제", "content_pin": "공지 고정",
    "strip_save": "띠배너 설정",
}


@bp.route("/logs")
@admin_required
def logs():
    q = (request.args.get("q") or "").strip()[:40] or None
    action = request.args.get("action") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    page, per_page = _page()
    rows, total = admin_log.list_admin(q, action, date_from, date_to, page, per_page)
    return render_template("admin/logs.html", rows=rows, q=q, action=action, date_from=date_from, date_to=date_to,
                           page=page, total_pages=max(1, -(-total // per_page)), total=total,
                           actions=admin_log.distinct_actions(), action_label=ACTION_LABEL)
