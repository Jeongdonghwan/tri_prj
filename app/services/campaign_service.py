"""캠페인: 견적(표시용), 등록(즉시 running + 순위 추적 시작), 상태전이, 순위 기록."""
import math
import secrets
from datetime import date, datetime

from ..constants import DISCOUNT_RULES, TRANSITIONS, VAT_RATE
from ..models import campaign as campaign_model
from ..models import media as media_model


class CampaignError(Exception):
    pass


# ---- quote ---------------------------------------------------------------
def quote(unit_price, daily_qty, days):
    order = int(unit_price) * int(daily_qty) * int(days)
    discount = 0
    for minimum, rate in DISCOUNT_RULES:
        if order >= minimum:
            discount = int(round(order * rate))
            break
    supply = order - discount
    vat = int(round(supply * VAT_RATE))
    return {"order": order, "discount": discount, "supply": supply, "vat": vat, "total": supply + vat,
            "days": int(days), "daily_qty": int(daily_qty), "unit_price": int(unit_price)}


def days_between(start, end):
    return (end - start).days + 1


# ---- create ----------------------------------------------------------------
def new_order_no():
    for _ in range(20):
        no = "N" + "".join(str(secrets.randbelow(10)) for _ in range(9))
        if not campaign_model.order_no_exists(no):
            return no
    raise CampaignError("order_no allocation failed")


def create(user, media, form):
    """등록 즉시 running 으로 시작하고 순위 서버에 추적을 건다 (결제 플로우 없음).

    순위 추적 실패는 캠페인 등록을 막지 않는다 — track_status='error' 로만 기록.
    같은 키워드·상품이 오늘 이미 수집돼 있으면(캐시 히트) 응답의 rank 를 즉시 기록해
    등록 직후 화면에서 시작 순위가 보인다.
    """
    days = days_between(form["start_date"], form["end_date"])
    q = quote(media["unit_price"], form["daily_qty"], days)
    cid = campaign_model.insert({
        "order_no": new_order_no(), "user_id": user["id"], "channel": media["channel"], "media_id": media["id"],
        "status": "running",
        "biz_name": form["biz_name"], "product_name": form.get("product_name"), "target_url": form["target_url"],
        "main_keyword": form["main_keyword"], "sub_keywords": form.get("sub_keywords") or [],
        "setting_keywords": form.get("setting_keywords") or [], "keyword_mode": form.get("keyword_mode", "ai"),
        "extra": form.get("extra") or {},
        "start_date": form["start_date"], "end_date": form["end_date"],
        "daily_qty": form["daily_qty"], "total_qty": form["daily_qty"] * days,
        "unit_price": media["unit_price"], "discount": q["discount"], "vat": q["vat"], "paid_amount": q["total"],
        "pay_method": "card", "warn_words": form.get("warn_words"),
    })
    campaign_model.add_log(cid, "running", "running", user["id"], "등록 · 순위 추적 시작")
    campaign = campaign_model.get(cid)
    start_tracking(campaign)
    return campaign_model.get(cid)


def start_tracking(campaign):
    """순위 서버에 추적 등록. 캐시 히트면 오늘 순위를 즉시 기록한다."""
    from datetime import date as _date
    from . import rank_client
    r = rank_client.track(campaign["main_keyword"], campaign["target_url"], campaign.get("product_name"))
    if r.get("ok"):
        campaign_model.update(campaign["id"], {"track_id": r["trackId"], "track_status": r["status"]})
        if r.get("prodNm") and not campaign.get("product_name"):
            campaign_model.update(campaign["id"], {"product_name": r["prodNm"][:120]})
        if r.get("status") == "collected":       # 캐시 히트 — 오늘 순위 즉시 반영
            record_rank(campaign_model.get(campaign["id"]), _date.today(), r.get("rank"), 0)
    else:
        campaign_model.update(campaign["id"], {"track_status": "error"})


# ---- transition ----------------------------------------------------------
def transition(campaign, to_status, actor_id=None, memo=None):
    """The only way to change campaigns.status. Validates the table, writes status_log, handles refunds."""
    frm = campaign["status"]
    if to_status not in TRANSITIONS.get(frm, set()):
        raise CampaignError(f"허용되지 않는 상태 변경: {frm} → {to_status}")
    campaign_model.set_status(campaign["id"], to_status)
    campaign_model.add_log(campaign["id"], frm, to_status, actor_id, memo)
    _notify_status(campaign, frm, to_status, memo)
    fresh = campaign_model.get(campaign["id"])
    if to_status == "done":
        _maybe_untrack(fresh)
    return fresh


_NOTIFY_TITLES = {
    "done": "캠페인이 완료되었습니다", "stopped": "캠페인이 중단되었습니다",
}


def _notify_status(campaign, frm, to_status, memo):
    from . import notify_service
    title = _NOTIFY_TITLES.get(to_status)
    if not title:
        return
    ntype = "campaign"
    notify_service.push(campaign["user_id"], ntype, f"[{campaign['order_no']}] {title}",
                        f"/campaign/{campaign['channel']}?open={campaign['id']}")




def stop(campaign, actor_id, reason="사용자 중단 요청"):
    """running -> stopped + 순위 추적 해제 (같은 추적을 쓰는 다른 진행 캠페인이 없을 때만)."""
    if campaign["status"] != "running":
        raise CampaignError("진행 중인 캠페인만 중단할 수 있습니다.")
    c = transition(campaign, "stopped", actor_id, reason)
    _maybe_untrack(c)
    return campaign_model.get(c["id"])


def _maybe_untrack(campaign):
    if not campaign.get("track_id"):
        return
    from ..db import query_one
    from . import rank_client
    other = query_one("SELECT id FROM campaigns WHERE track_id = %s AND status = 'running' AND id != %s LIMIT 1",
                      (campaign["track_id"], campaign["id"]))
    if other is None:
        rank_client.untrack(campaign["track_id"])


def record_rank(campaign, day, rank, done_qty, actor_id=None):
    if campaign["status"] not in ("running", "approved", "done"):
        raise CampaignError("진행 중인 캠페인만 순위를 입력할 수 있습니다.")
    campaign_model.upsert_daily(campaign["id"], day, rank, done_qty)
    fields = {"rank_now": rank}
    if campaign["rank_start"] is None:
        fields["rank_start"] = rank
    campaign_model.update(campaign["id"], fields)
    return campaign_model.get(campaign["id"])


# ---- progress helpers (templates) -----------------------------------------
def progress(campaign, today=None):
    """{'total', 'elapsed', 'pct', 'label', 'sub', 'cls'} for the manage table progress cell."""
    today = today or date.today()
    total = days_between(campaign["start_date"], campaign["end_date"])
    st = campaign["status"]
    if st in ("pay_wait", "review", "approved"):
        return {"cls": "wait", "pct": 0, "label": f"{campaign['start_date']:%m.%d} 시작", "sub": f"{total}일", "total": total, "elapsed": 0}
    if st == "rejected":
        return {"cls": "rej", "pct": 0, "label": (campaign.get("reject_reason") or "반려"), "sub": "전액 환불", "total": total, "elapsed": 0}
    if st == "cancelled":
        return {"cls": "rej", "pct": 0, "label": "취소됨", "sub": "", "total": total, "elapsed": 0}
    elapsed = max(0, min(total, (today - campaign["start_date"]).days + 1))
    if st == "done":
        elapsed = total
    pct = int(elapsed / total * 100) if total else 0
    sub = f"{campaign['end_date']:%m.%d} 종료"
    if st == "stopped":
        sub = "중단"
    return {"cls": "done" if st in ("done", "stopped") else "", "pct": pct, "label": f"{elapsed} / {total}일", "sub": sub,
            "total": total, "elapsed": elapsed}


def day_index(campaign, today=None):
    today = today or date.today()
    return max(0, (today - campaign["start_date"]).days + 1)
