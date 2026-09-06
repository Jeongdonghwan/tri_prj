"""/campaign/store — 관리 목록(등록/수정 모달)/드로어/순위표.

캠페인은 어드민이 발급한다(/admin/users). 사용자는 목록에서 키워드·상품·URL 만
등록/수정하면 되고, 등록하는 순간 순위 추적이 시작된다. 결제·생성 화면 없음.
"""
from datetime import date, timedelta

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for)

from ..constants import CHANNEL_LABEL, STATUS_CLASS, STATUS_LABEL, STATUS_ORDER
from ..models import admin_log
from ..models import campaign as campaign_model
from ..services import campaign_service, forbidden_service, rank_client, url_service
from .auth import login_required


def _audit(action, campaign, summary):
    """사용자 캠페인 동작을 로그 기록(admin_log)에도 남긴다 (변경 이력과 별개의 시간순 감사 로그)."""
    admin_log.log(g.user["id"], action, "campaign", campaign["id"], summary)

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
    q = (request.args.get("q") or "").strip()[:60] or None
    page = max(1, request.args.get("page", 1, type=int))
    per_page = current_app.config["PER_PAGE"]
    rows = campaign_model.list_user(uid, channel, status, period, q, page, per_page)
    total = campaign_model.count_user(uid, channel, status, period, q)
    for r in rows:
        r["prog"] = campaign_service.progress(r)
    # 자동 보정(비차단): 진행 중인데 ①순위/상품명 누락(콜백 유실) 또는 ②추적 자체가 실패(track error)인 슬롯
    stale = [r["id"] for r in rows if r["status"] == "running"
             and (r.get("rank_now") is None or not r.get("product_name")
                  or not r.get("track_id") or r.get("track_status") == "error")]
    if stale:
        _reconcile_async(stale)
    counts = campaign_model.status_counts(uid, channel)
    avg_up, done_n = campaign_model.avg_rank_change(uid, channel)
    stats = {"running": counts.get("running", 0), "pending": counts.get("pending", 0),
             "avg_up": avg_up, "done_n": done_n}
    return render_template(
        "campaign/manage.html", channel=channel, channels=CHANNELS, rows=rows, page=page,
        total_pages=max(1, -(-total // per_page)), counts=counts, total_all=sum(counts.values()),
        status=status, period=period, q=q, stats=stats,
        status_order=STATUS_ORDER, status_label=STATUS_LABEL, status_class=STATUS_CLASS,
        open_id=request.args.get("open", type=int),
    )


# =============================================================== 등록/수정 (모달 제출)
def _parse_fill(channel, form):
    """등록/수정 모달 검증. (data, error)"""
    f = {}
    f["product_name"] = (form.get("product_name") or "").strip()[:120] or None
    try:
        f["target_url"] = url_service.normalize(form.get("target_url"), channel)
    except url_service.URLError as e:
        return None, str(e)
    f["main_keyword"] = " ".join((form.get("main_keyword") or "").split())[:60]
    if not f["main_keyword"]:
        return None, "순위 키워드를 입력해주세요."
    found = forbidden_service.check([f["product_name"] or "", f["main_keyword"]], channel)
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
    _audit("campaign_register" if was_pending else "campaign_edit", c,
           f"슬롯{c['slot_no']} {'등록' if was_pending else '수정'} · {c['main_keyword']}"
           f" · {c['start_date']}~{c['end_date']}")
    if c.get("track_status") == "collected" and c.get("rank_now"):
        flash(f"{'등록' if was_pending else '수정'}되었습니다. 현재 순위 {c['rank_now']}위 (즉시 조회됨)")
    elif c.get("track_status") == "error":
        flash(f"{'등록' if was_pending else '수정'}되었습니다. 순위 조회 연결이 지연되고 있어 잠시 후 자동 반영됩니다.")
    else:
        flash(f"{'등록' if was_pending else '수정'}되었습니다. 첫 순위는 몇 분 내 자동 조회됩니다.")
    return redirect(url_for("campaign.manage", channel=channel, open=c["id"]))


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


def _reconcile_async(campaign_ids):
    """순위/상품명 누락 진행 슬롯을 백그라운드에서 순위 서버와 재동기화 (페이지 응답을 막지 않음)."""
    import threading
    app = current_app._get_current_object()

    def run():
        import time as _t
        with app.app_context():
            for cid in campaign_ids:
                try:
                    c = campaign_model.get(cid)
                    if not c or c["status"] != "running":
                        continue
                    if not c.get("track_id") or c.get("track_status") == "error":
                        # 추적 등록 자체가 실패한 슬롯 → 자동 재추적 (5분 스로틀)
                        if _t.time() - _FB_CACHE.get(("track", cid), 0) < 300:
                            continue
                        _FB_CACHE[("track", cid)] = _t.time()
                        if c.get("main_keyword") and c.get("target_url"):
                            current_app.logger.info("추적 자동 재시도 campaign=%s kw=%s", cid, c["main_keyword"])
                            campaign_service.start_tracking(c)
                    else:
                        _fallback_sync(c)
                except Exception:
                    current_app.logger.exception("재동기화 실패 campaign=%s", cid)

    threading.Thread(target=run, daemon=True).start()


def _fallback_sync(c):
    """콜백 유실 대비: 진행 중 + 오늘 순위 없음 + 5분 경과 시 순위 서버 이력으로 보정."""
    import time as _t
    if c["status"] != "running" or not c.get("track_id"):
        return
    if campaign_model.today_rank(c["id"]) is not None and c.get("product_name"):
        return                                   # 순위·상품명 다 있으면 재조회 불필요
    last = _FB_CACHE.get(c["id"], 0)
    if _t.time() - last < 300:
        return
    _FB_CACHE[c["id"]] = _t.time()
    r = rank_client.fetch_ranks(c["track_id"])
    if not r.get("ok"):
        return
    if r.get("prodNm") and not c.get("product_name"):    # 콜백 유실 시 상품명도 폴백으로 보정
        campaign_model.update(c["id"], {"product_name": r["prodNm"][:120]})
    have = {d["date"] for d in campaign_model.list_daily(c["id"])}
    for row in r.get("ranks", []):
        d = date.fromisoformat(row["date"])
        if c["start_date"] <= d <= min(date.today(), c["end_date"]) and d not in have:
            try:
                campaign_service.record_rank(c, d, row["rank"])
            except campaign_service.CampaignError:
                return


@bp.route("/<channel>/bulk-fill", methods=["POST"])
@login_required
def bulk_fill(channel):
    """체크박스로 선택한 슬롯들에 같은 키워드·URL 을 한 번에 등록/수정."""
    _channel(channel)
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    if not ids:
        flash("슬롯을 선택해주세요.")
        return redirect(url_for("campaign.manage", channel=channel))
    data, err = _parse_fill(channel, request.form)
    if err:
        flash(err)
        return redirect(url_for("campaign.manage", channel=channel))
    import secrets
    batch_id = secrets.token_hex(8)          # 이 일괄 등록을 변경 이력에서 한 줄로 묶는 키
    ok, slots, msgs = 0, [], []
    for cid in ids:
        c = campaign_model.get(cid)
        if not c or c["user_id"] != g.user["id"] or c["channel"] != channel:
            continue
        try:
            c2 = campaign_service.fill(c, g.user, data, batch_id=batch_id)
            ok += 1
            slots.append(str(c2["slot_no"]))
        except campaign_service.CampaignError as e:
            msgs.append(f"슬롯{c['slot_no']}: {e}")
    if ok:
        _audit("campaign_register", campaign_model.get(int(ids[0])),
               f"슬롯 {', '.join(slots)} ({ok}개) 일괄 등록 · {data['main_keyword']}")
    flash(f"{ok}개 슬롯에 등록했습니다. 순위는 자동 조회됩니다." + (" · " + "; ".join(msgs[:3]) if msgs else ""))
    return redirect(url_for("campaign.manage", channel=channel))


@bp.route("/<channel>/<int:campaign_id>/stop", methods=["POST"])
@login_required
def stop(channel, campaign_id):
    c = _own(_channel(channel), campaign_id)
    try:
        c = campaign_service.stop(c, g.user["id"])
        _audit("campaign_stop", c, f"슬롯{c['slot_no']} 중단 · {c['main_keyword'] or ''}")
        flash("캠페인을 중단했습니다. 순위 추적도 종료됩니다.")
    except campaign_service.CampaignError as e:
        flash(str(e))
    return redirect(url_for("campaign.manage", channel=channel, open=c["id"]))
