"""/campaign/store — 관리 목록(등록/수정 모달)/드로어/순위표.

캠페인은 어드민이 발급한다(/admin/users). 사용자는 목록에서 키워드·상품·URL 만
등록/수정하면 되고, 등록하는 순간 순위 추적이 시작된다. 결제·생성 화면 없음.
"""
from datetime import date, timedelta

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for)

from ..constants import CHANNEL_LABEL, STATUS_CLASS, STATUS_LABEL, STATUS_ORDER
from ..models import campaign as campaign_model
from ..services import campaign_service, forbidden_service, rank_client, url_service
from .auth import login_required

bp = Blueprint("campaign", __name__, url_prefix="/campaign")

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
    avg_up, done_n = campaign_model.avg_rank_change(uid, channel)
    stats = {"running": counts.get("running", 0), "pending": counts.get("pending", 0),
             "avg_up": avg_up, "done_n": done_n}
    return render_template(
        "campaign/manage.html", channel=channel, channels=CHANNELS, rows=rows, page=page,
        total_pages=max(1, -(-total // per_page)), counts=counts, total_all=sum(counts.values()),
        status=status, period=period, media_id=media_id, q=q, stats=stats,
        media_options=campaign_model.media_used(uid, channel),
        status_order=STATUS_ORDER, status_label=STATUS_LABEL, status_class=STATUS_CLASS,
        open_id=request.args.get("open", type=int),
    )


# =============================================================== 등록/수정 (모달 제출)
def _parse_fill(channel, form):
    """등록/수정 모달 검증. (data, error)"""
    f = {}
    f["product_name"] = (form.get("product_name") or "").strip()[:120]
    if not f["product_name"]:
        return None, "상품명을 입력해주세요."
    try:
        f["target_url"] = url_service.normalize(form.get("target_url"), channel)
    except url_service.URLError as e:
        return None, str(e)
    f["main_keyword"] = " ".join((form.get("main_keyword") or "").split())[:60]
    if not f["main_keyword"]:
        return None, "순위 키워드를 입력해주세요."
    found = forbidden_service.check([f["product_name"], f["main_keyword"]], channel)
    if found["block"]:
        return None, f"사용할 수 없는 문구가 포함되어 있습니다: {', '.join(found['block'])}"
    f["warn_words"] = ", ".join(found["warn"]) or None
    return f, None


@bp.route("/<channel>/<int:campaign_id>/fill", methods=["POST"])
@login_required
def fill(channel, campaign_id):
    c = _own(_channel(channel), campaign_id)
    data, err = _parse_fill(channel, request.form)
    if err:
        flash(err)
        return redirect(url_for("campaign.manage", channel=channel, open=c["id"]))
    was_pending = c["status"] == "pending"
    try:
        c = campaign_service.fill(c, g.user, data)
    except campaign_service.CampaignError as e:
        flash(str(e))
        return redirect(url_for("campaign.manage", channel=channel))
    if c.get("track_status") == "collected" and c.get("rank_now"):
        flash(f"{'등록' if was_pending else '수정'}되었습니다. 현재 순위 {c['rank_now']}위 (즉시 조회됨)")
    elif c.get("track_status") == "error":
        flash(f"{'등록' if was_pending else '수정'}되었습니다. 순위 조회 연결이 지연되고 있어 잠시 후 자동 반영됩니다.")
    else:
        flash(f"{'등록' if was_pending else '수정'}되었습니다. 첫 순위는 몇 분 내 자동 조회됩니다.")
    return redirect(url_for("campaign.manage", channel=channel, open=c["id"]))


@bp.route("/<channel>/<int:campaign_id>/drawer")
@login_required
def drawer(channel, campaign_id):
    c = _own(_channel(channel), campaign_id)
    daily = campaign_model.list_daily(c["id"])
    ranks = [d for d in daily if d["rank"]]
    best = min((d["rank"] for d in ranks), default=None)
    worst = max((d["rank"] for d in ranks), default=None)
    for d in ranks:
        # 순위가 높을수록(숫자가 작을수록) 막대가 길다
        d["h"] = 100 if worst == best else int(30 + (worst - d["rank"]) / (worst - best) * 70)
    return render_template(
        "campaign/_drawer.html", channel=channel, c=c, daily=daily, ranks=ranks[-14:],
        done_qty=campaign_model.total_done_qty(c["id"]), logs=campaign_model.list_log(c["id"]),
        prog=campaign_service.progress(c), day_idx=campaign_service.day_index(c),
        status_label=STATUS_LABEL, status_class=STATUS_CLASS,
    )


@bp.route("/<channel>/<int:campaign_id>/ranks")
@login_required
def ranks(channel, campaign_id):
    """일자별 순위 모달. 오늘 순위가 비어 있으면 순위 서버에서 폴백 조회."""
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
