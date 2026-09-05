"""/campaign/store — 등록(즉시 진행+순위 추적), 관리 목록/드로어/순위표, 쇼핑 슬롯."""
import json
from datetime import date, datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, session,
                   url_for)

from ..constants import (CHANNEL_LABEL, DATE_PRESETS, STATUS_CLASS, STATUS_LABEL, STATUS_ORDER,
                         STORE_SLOT_MAX, reco_qty)
from ..models import campaign as campaign_model
from ..models import content as content_model
from ..models import media as media_model
from ..models import store_slot as slot_model
from ..services import campaign_service, forbidden_service, keyword_service, rank_client, url_service
from .auth import login_required
from .main import render_placeholder



bp = Blueprint("campaign", __name__, url_prefix="/campaign")
api = Blueprint("campaign_api", __name__, url_prefix="/api/campaign")

CHANNELS = CHANNEL_LABEL


def _channel(channel):
    if channel not in CHANNELS:
        abort(404)
    return channel


def _own(channel, campaign_id):
    c = campaign_model.get(campaign_id)
    if not c or c["user_id"] != g.user["id"] or c["channel"] != channel:
        abort(404)
    return c


# =============================================================== create
def _media_ctx(channel):
    """Media tiles grouped into fixed sections (리워드/유입/복합, stored in media.group_name)."""
    from ..constants import MEDIA_SECTIONS
    medias = media_model.list_by_channel(channel)
    for m in medias:
        m["initial"] = m["name"][:1]
    medias.sort(key=lambda m: (0 if m["badge"] == "rec" else 1, m["sort"], m["unit_price"]))
    sections = []
    for name in MEDIA_SECTIONS:
        items = [m for m in medias if m["group_name"] == name]
        if items:
            sections.append({"name": name, "items": items})
    rest = [m for m in medias if m["group_name"] not in MEDIA_SECTIONS]
    if rest:
        sections.append({"name": "기타", "items": rest})
    return medias, sections


def _prefill(channel):
    """Prefill from ?copy=, ?edit=, ?slot= or session 'campaign_prefill'."""
    pre, editing = {}, None
    cid = request.args.get("copy", type=int)
    xid = request.args.get("extend", type=int)
    eid = request.args.get("edit", type=int)
    sid = request.args.get("slot", type=int)
    if eid:
        flash("등록 즉시 진행되는 구조라 주문 수정은 지원하지 않습니다. 중단 후 재등록해 주세요.")
        return redirect(url_for("campaign.manage", channel=channel))
    elif cid or xid:
        src = _own(channel, cid or xid)
        pre = {k: src[k] for k in ("media_id", "biz_name", "product_name", "target_url", "main_keyword", "sub_keywords",
                                    "setting_keywords", "keyword_mode", "extra", "daily_qty")}
        pre["media_id"] = src["media_id"]
        if xid:
            days = (src["end_date"] - src["start_date"]).days + 1
            start = _next_weekday(max(date.today(), src["end_date"] + timedelta(days=1)))
            pre["start_date"] = start.isoformat()
            pre["end_date"] = (start + timedelta(days=days - 1)).isoformat()
            flash(f"{src['order_no']} 기간 연장 — 기존 종료일 다음 영업일부터 같은 설정으로 이어집니다.")
    elif sid and channel == "store":
        s = slot_model.get(sid, g.user["id"])
        if s:
            pre = {"main_keyword": s["keyword"], "target_url": s["product_url"] or "", "biz_name": s["store_name"] or "",
                   "daily_qty": s["reco_qty"], "slot_reco": s["reco_qty"]}
    elif session.get("campaign_prefill"):
        pre = session.pop("campaign_prefill")
    if "media_id" not in pre and request.args.get("media", type=int):
        pre["media_id"] = request.args.get("media", type=int)
    return pre, editing


def _next_weekday(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


@bp.route("/<channel>/new", methods=["GET", "POST"])
@login_required
def new(channel):
    _channel(channel)
    if request.method == "POST":
        return _create(channel)
    pre = _prefill(channel)
    if not isinstance(pre, tuple):
        return pre
    pre, editing = pre
    medias, sections = _media_ctx(channel)
    now = datetime.now()
    start = _next_weekday(now.date() + (timedelta(days=1) if now.strftime("%H:%M") >= "13:30" else timedelta(days=0)))
    if not pre.get("start_date"):
        pre["start_date"] = start
        pre["end_date"] = start + timedelta(days=9)
    return render_template(
        "campaign/new.html", channel=channel, channels=CHANNELS, sections=sections,
        pre=pre, editing=editing, presets=DATE_PRESETS,
        media_json=json.dumps({m["id"]: {"name": m["name"], "price": m["unit_price"], "list": m["list_price"],
                                         "min_days": m["min_days"], "min_daily": m["min_daily"], "max_daily": m["max_daily"],
                                         "tagline": m["tagline"], "eff": m["eff_level"], "eff_note": m["eff_note"] or "",
                                         "same_day": bool(m["same_day"]), "cutoff": str(m["cutoff_time"])[:5],
                                         "desc": m["description"] or ""} for m in medias},
                              ensure_ascii=False),
        is_debug=current_app.debug,
    )


def _parse_form(channel, media, form):
    """Validate the create/edit form. Returns (data, error_message)."""
    f = {}
    try:
        f["start_date"] = date.fromisoformat(form.get("start_date", ""))
        f["end_date"] = date.fromisoformat(form.get("end_date", ""))
    except ValueError:
        return None, "기간을 선택해주세요."
    if f["end_date"] < f["start_date"]:
        return None, "종료일이 시작일보다 빠릅니다."
    if f["start_date"] < date.today():
        return None, "시작일은 오늘 이후여야 합니다."
    days = campaign_service.days_between(f["start_date"], f["end_date"])
    if days < media["min_days"]:
        return None, f"이 매체는 최소 {media['min_days']}일 이상 설정해야 합니다."
    if days > 60:
        return None, "기간은 최대 60일입니다."
    try:
        f["daily_qty"] = int(form.get("daily_qty", "0"))
    except ValueError:
        return None, "일 작업량을 입력해주세요."
    if not (media["min_daily"] <= f["daily_qty"] <= media["max_daily"]):
        return None, f"일 작업량은 {media['min_daily']}~{media['max_daily']}건입니다."

    f["biz_name"] = (form.get("biz_name") or "").strip()[:80]
    f["product_name"] = (form.get("product_name") or "").strip()[:120] or None
    if not f["product_name"]:
        return None, "상품명을 입력해주세요."
    f["biz_name"] = f["product_name"]
    try:
        f["target_url"] = url_service.normalize(form.get("target_url"), channel)
    except url_service.URLError as e:
        return None, str(e)
    f["main_keyword"] = " ".join((form.get("main_keyword") or "").split())[:60]
    if not f["main_keyword"]:
        return None, "희망 키워드를 입력해주세요."
    f["sub_keywords"] = []
    f["keyword_mode"] = "manual"
    f["setting_keywords"] = [f["main_keyword"]]
    f["extra"] = {}

    found = forbidden_service.check([f["biz_name"], f["product_name"], f["main_keyword"]], channel)
    if found["block"]:
        return None, f"사용할 수 없는 문구가 포함되어 있습니다: {', '.join(found['block'])}"
    f["warn_words"] = ", ".join(found["warn"]) or None
    return f, None


def _create(channel):
    media_id = request.form.get("media_id", type=int)
    media = media_model.get(media_id) if media_id else None
    if not media or media["channel"] != channel or not media["is_active"]:
        flash("매체사를 선택해주세요.")
        return redirect(url_for("campaign.new", channel=channel))
    data, err = _parse_form(channel, media, request.form)
    if err:
        flash(err)
        session["campaign_prefill"] = {k: v for k, v in request.form.items() if k not in ("csrf",)}
        session["campaign_prefill"]["media_id"] = media_id
        return redirect(url_for("campaign.new", channel=channel, edit=request.form.get("edit_id") or None))
    try:
        c = campaign_service.create(g.user, media, data)
    except campaign_service.CampaignError as e:
        flash(str(e))
        return redirect(url_for("campaign.new", channel=channel))
    if c.get("track_status") == "collected" and c.get("rank_now"):
        flash(f"캠페인이 등록되었습니다. 현재 순위 {c['rank_now']}위 (즉시 조회됨)")
    elif c.get("track_status") == "error":
        flash("캠페인이 등록되었습니다. 순위 조회 연결이 지연되고 있어 잠시 후 자동 반영됩니다.")
    else:
        flash("캠페인이 등록되었습니다. 첫 순위는 몇 분 내 자동 조회됩니다.")
    return redirect(url_for("campaign.manage", channel=channel, open=c["id"]))


# =============================================================== manage
@bp.route("/<channel>")
@login_required
def manage(channel):
    _channel(channel)
    uid = g.user["id"]
    status = request.args.get("status") or None
    if status and status not in STATUS_LABEL:
        status = None
    period = request.args.get("period") or None
    media_id = request.args.get("media", type=int)
    q = (request.args.get("q") or "").strip()[:60] or None
    page = max(1, request.args.get("page", 1, type=int))
    per_page = current_app.config["PER_PAGE"]
    rows = campaign_model.list_user(uid, channel, status, period, media_id, q, page, per_page)
    total = campaign_model.count_user(uid, channel, status, period, media_id, q)
    for r in rows:
        r["prog"] = campaign_service.progress(r)
    counts = campaign_model.status_counts(uid, channel)
    running = counts.get("running", 0)
    avg_up, done_n = campaign_model.avg_rank_change(uid, channel)
    month, last = campaign_model.month_paid(uid, channel), campaign_model.last_month_paid(uid, channel)
    delta = None if not last else int((month - last) / last * 100)
    stats = {
        "running": running, "today_spend": campaign_model.running_today_spend(uid, channel),
        "waiting": 0,
        "month_paid": month, "delta": delta, "avg_up": avg_up, "done_n": done_n,
    }
    return render_template(
        "campaign/manage.html", channel=channel, channels=CHANNELS, rows=rows, page=page,
        total_pages=max(1, -(-total // per_page)), counts=counts, total_all=sum(counts.values()),
        status=status, period=period, media_id=media_id, q=q, stats=stats,
        media_options=campaign_model.media_used(uid, channel),
        status_order=STATUS_ORDER, status_label=STATUS_LABEL, status_class=STATUS_CLASS,
        open_id=request.args.get("open", type=int),
    )


@bp.route("/<channel>/<int:campaign_id>/drawer")
@login_required
def drawer(channel, campaign_id):
    c = _own(_channel(channel), campaign_id)
    daily = campaign_model.list_daily(c["id"])
    ranks = [d for d in daily if d["rank"]]
    best = min((d["rank"] for d in ranks), default=None)
    worst = max((d["rank"] for d in ranks), default=None)
    for d in ranks:
        # lower rank = taller bar
        d["h"] = 100 if worst == best else int(30 + (worst - d["rank"]) / (worst - best) * 70)
    return render_template(
        "campaign/_drawer.html", channel=channel, c=c, p=None, daily=daily, ranks=ranks[-14:],
        done_qty=campaign_model.total_done_qty(c["id"]), logs=campaign_model.list_log(c["id"]),
        prog=campaign_service.progress(c), day_idx=campaign_service.day_index(c),
        status_label=STATUS_LABEL, status_class=STATUS_CLASS,
    )


@bp.route("/<channel>/<int:campaign_id>/ranks")
@login_required
def ranks(channel, campaign_id):
    """관리 목록에서 여는 일자별 순위 모달. 오늘 순위가 비어 있으면 순위 서버에서 폴백 조회."""
    _channel(channel)
    c = _own(channel, campaign_id)
    _fallback_sync(c)
    rankmap = {d["date"]: d["rank"] for d in campaign_model.list_daily(campaign_id)}
    days, cur = [], min(date.today(), c["end_date"])
    while cur >= c["start_date"]:
        days.append({"date": cur, "rank": rankmap.get(cur)})
        cur -= timedelta(days=1)
    today_rank = rankmap.get(date.today())
    delta = (c["rank_start"] - today_rank) if (c["rank_start"] and today_rank) else None
    return render_template("campaign/_ranks.html", c=c, channel=channel, days=days,
                           today_rank=today_rank, delta=delta,
                           wd=["월", "화", "수", "목", "금", "토", "일"])


_FB_CACHE = {}

def _fallback_sync(c):
    """콜백 유실 대비: 진행 중 + 오늘 순위 없음 + 5분 경과 시 순위 서버 이력으로 보정."""
    import time as _t
    if c["status"] != "running" or not c.get("track_id"):
        return
    if campaign_model.today_rank(c["id"]) is not None:
        return
    last = _FB_CACHE.get(c["id"], 0)
    if _t.time() - last < 300:
        return
    _FB_CACHE[c["id"]] = _t.time()
    r = rank_client.fetch_ranks(c["track_id"])
    if not r.get("ok"):
        return
    have = {d["date"] for d in campaign_model.list_daily(c["id"])}
    for row in r.get("ranks", []):
        d = date.fromisoformat(row["date"])
        if c["start_date"] <= d <= min(date.today(), c["end_date"]) and d not in have:
            try:
                campaign_service.record_rank(c, d, row["rank"], 0)
            except campaign_service.CampaignError:
                return


@bp.route("/<channel>/<int:campaign_id>/stop", methods=["POST"])
@login_required
def stop(channel, campaign_id):
    c = _own(_channel(channel), campaign_id)
    try:
        c = campaign_service.stop(c, g.user["id"])
        flash("캠페인을 중단했습니다. 순위 추적도 종료됩니다.")
    except campaign_service.CampaignError as e:
        flash(str(e))
    return redirect(url_for("campaign.manage", channel=channel, open=c["id"]))


# =============================================================== store slots (2-4-1, standalone page)
@bp.route("/store/slots")
@login_required
def slots():
    return render_template("campaign/slots.html", channel="store", channels=CHANNELS, store=_store_hub_ctx())


def _store_hub_ctx():
    uid = g.user["id"]
    slots = slot_model.list_user(uid)
    for s in slots:
        s["total"] = s["pc_cnt"] + s["mo_cnt"]
        s["daily"] = round(s["total"] / 30)
    notices = content_model.list_channel_notices("store", 1)
    return {
        "slots": slots, "slot_max": STORE_SLOT_MAX, "slot_used": len(slots),
        "notice": notices[0] if notices else None, "notice_count": content_model.count_channel_notices("store"),
        "running": campaign_model.list_recent_channel(uid, "store", 5),
    }


@bp.route("/store/slots", methods=["POST"])
@login_required
def slot_add():
    kw = " ".join((request.form.get("keyword") or "").split())[:60]
    if not kw:
        flash("상품 키워드를 입력해주세요.")
    elif slot_model.count_user(g.user["id"]) >= STORE_SLOT_MAX:
        flash(f"슬롯은 최대 {STORE_SLOT_MAX}개입니다.")
    else:
        url = (request.form.get("product_url") or "").strip()[:500]
        if url:
            try:
                url = url_service.normalize(url, "store")
            except url_service.URLError as e:
                flash(str(e))
                return redirect(url_for("campaign.slots"))
        pc, mo = keyword_service.search_volume(kw)
        slot_model.insert(g.user["id"], kw, url, (request.form.get("store_name") or "").strip()[:80], pc, mo, reco_qty(pc + mo))
        flash(f"'{kw}' 슬롯을 등록했습니다.")
    return redirect(url_for("campaign.slots"))


@bp.route("/store/slots/<int:slot_id>/delete", methods=["POST"])
@login_required
def slot_delete(slot_id):
    slot_model.delete(slot_id, g.user["id"])
    return redirect(url_for("campaign.slots"))


# =============================================================== JSON API
@api.route("/quote", methods=["POST"])
def api_quote():
    d = request.get_json(silent=True) or request.form
    media = media_model.get(int(d.get("media_id", 0) or 0))
    if not media:
        return jsonify(ok=False, error="media"), 400
    try:
        s, e = date.fromisoformat(d["start_date"]), date.fromisoformat(d["end_date"])
        qty = int(d["daily_qty"])
    except (KeyError, ValueError):
        return jsonify(ok=False, error="input"), 400
    days = campaign_service.days_between(s, e)
    return jsonify(ok=True, **campaign_service.quote(media["unit_price"], qty, days))


@api.route("/keywords")
def api_keywords():
    return jsonify(keywords=keyword_service.suggest_setting_keywords(request.args.get("kw", ""), request.args.get("channel", "place")))


@api.route("/volume")
def api_volume():
    kw = (request.args.get("kw") or "").strip()
    if not kw:
        return jsonify(ok=False)
    pc, mo = keyword_service.search_volume(kw)
    return jsonify(ok=True, pc=pc, mo=mo, total=pc + mo, daily=round((pc + mo) / 30), reco=reco_qty(pc + mo))
