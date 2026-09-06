"""캠페인: 어드민 발급(빈 슬롯) → 사용자 등록/수정(fill, 순위 추적 시작) → 상태전이 · 순위 기록.

결제·금액 개념 없음. 기간·수량은 어드민이 발급/수정하고, 사용자는 키워드·상품·URL 만 다룬다.
"""
from datetime import date

from ..constants import TRANSITIONS
from ..models import campaign as campaign_model


class CampaignError(Exception):
    pass


def days_between(start, end):
    return (end - start).days + 1


# ---- 발급 (어드민) ---------------------------------------------------------
def issue(admin_id, user, start_date, end_date, count=1):
    """빈 캠페인(등록 대기) count 개 발급. 슬롯번호는 계정마다 1부터 순차 부여."""
    if end_date < start_date:
        raise CampaignError("종료일이 시작일보다 빠릅니다.")
    if not (1 <= count <= 50):
        raise CampaignError("발급 개수는 1~50개입니다.")
    base = campaign_model.max_slot_no(user["id"])
    ids = []
    for i in range(count):
        cid = campaign_model.insert({
            "slot_no": base + 1 + i, "user_id": user["id"], "channel": "store",
            "status": "pending", "start_date": start_date, "end_date": end_date,
        })
        campaign_model.add_log(cid, "pending", "pending", admin_id, f"슬롯 발급 · {start_date}~{end_date}")
        ids.append(cid)
    _notify(user["id"], f"캠페인 슬롯 {count}개가 발급되었습니다. 키워드·상품을 등록해주세요.", "/campaign/store?status=pending")
    return ids


def update_terms(campaign, admin_id, start_date, end_date):
    """어드민 기간 수정."""
    if end_date < start_date:
        raise CampaignError("종료일이 시작일보다 빠릅니다.")
    campaign_model.update(campaign["id"], {"start_date": start_date, "end_date": end_date})
    campaign_model.add_log(campaign["id"], campaign["status"], campaign["status"], admin_id,
                           f"기간 변경 · {start_date}~{end_date}")
    return campaign_model.get(campaign["id"])


# ---- 등록/수정 (사용자) -----------------------------------------------------
def fill(campaign, user, data):
    """사용자 등록(빈 캠페인 채우기)/수정. 등록 대기 → running + 순위 추적 시작.

    진행 중 캠페인의 키워드·URL 이 바뀌면 추적을 갈아탄다
    (기존 슬롯은 다른 진행 캠페인이 안 쓰면 해제 → 새 슬롯 등록).
    """
    if campaign["status"] not in ("pending", "running"):
        raise CampaignError("등록 대기 또는 진행 중인 캠페인만 수정할 수 있습니다.")
    changed_track = (campaign.get("main_keyword") != data["main_keyword"]
                     or campaign.get("target_url") != data["target_url"])
    is_new = campaign["status"] == "pending"
    memo = _change_memo(campaign, data, is_new)
    campaign_model.update(campaign["id"], {
        "product_name": data.get("product_name"),
        "target_url": data["target_url"], "main_keyword": data["main_keyword"],
        "setting_keywords": [data["main_keyword"]],
        "warn_words": data.get("warn_words"),
    })
    fresh = campaign_model.get(campaign["id"])
    if is_new:
        fresh = transition(fresh, "running", user["id"], memo)
        start_tracking(fresh)
    elif changed_track:
        _maybe_untrack(campaign)                      # 기존 추적: 공유 검사 후 해제
        campaign_model.update(fresh["id"], {"track_id": None, "track_status": None,
                                            "rank_start": None, "rank_now": None})
        campaign_model.add_log(fresh["id"], "running", "running", user["id"], memo + " · 추적 재등록")
        start_tracking(campaign_model.get(fresh["id"]))
    else:
        campaign_model.add_log(fresh["id"], "running", "running", user["id"], memo)
    return campaign_model.get(campaign["id"])


def _change_memo(old, data, is_new):
    """변경 이력에 값까지 남긴다 (운영자가 다른 사이트에 옮겨 적을 수 있도록)."""
    if is_new:
        return f"등록 · 키워드 '{data['main_keyword']}' · URL {data['target_url']}"
    parts = []
    if (old.get("main_keyword") or "") != data["main_keyword"]:
        parts.append(f"키워드 '{old.get('main_keyword') or '-'}' → '{data['main_keyword']}'")
    if (old.get("target_url") or "") != data["target_url"]:
        parts.append(f"URL → {data['target_url']}")
    if (old.get("product_name") or "") != (data.get("product_name") or ""):
        parts.append(f"상품명 '{old.get('product_name') or '-'}' → '{data.get('product_name') or '-'}'")
    return "수정 · " + (", ".join(parts) if parts else "변경 없음")


def start_tracking(campaign):
    """순위 서버에 추적 등록. 캐시 히트면 오늘 순위를 즉시 기록한다."""
    from . import rank_client
    r = rank_client.track(campaign["main_keyword"], campaign["target_url"], campaign.get("product_name"))
    if r.get("ok"):
        campaign_model.update(campaign["id"], {"track_id": r["trackId"], "track_status": r["status"]})
        if r.get("prodNm") and not campaign.get("product_name"):
            campaign_model.update(campaign["id"], {"product_name": r["prodNm"][:120]})
        if r.get("status") == "collected":       # 캐시 히트 — 오늘 순위 즉시 반영
            record_rank(campaign_model.get(campaign["id"]), date.today(), r.get("rank"))
    else:
        campaign_model.update(campaign["id"], {"track_status": "error"})


# ---- transition ----------------------------------------------------------
def transition(campaign, to_status, actor_id=None, memo=None):
    """campaigns.status 를 바꾸는 유일한 경로. 전이표 검증 + status_log 기록."""
    frm = campaign["status"]
    if to_status not in TRANSITIONS.get(frm, set()):
        raise CampaignError(f"허용되지 않는 상태 변경: {frm} → {to_status}")
    campaign_model.set_status(campaign["id"], to_status)
    campaign_model.add_log(campaign["id"], frm, to_status, actor_id, memo)
    _notify_status(campaign, to_status)
    fresh = campaign_model.get(campaign["id"])
    if to_status == "done":
        _maybe_untrack(fresh)
    return fresh


_NOTIFY_TITLES = {"done": "캠페인이 완료되었습니다", "stopped": "캠페인이 중단되었습니다"}


def _notify(user_id, title, link):
    from . import notify_service
    notify_service.push(user_id, "campaign", title, link)


def _notify_status(campaign, to_status):
    title = _NOTIFY_TITLES.get(to_status)
    if title:
        _notify(campaign["user_id"], f"[슬롯 {campaign['slot_no']}] {title}",
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


def record_rank(campaign, day, rank, actor_id=None):
    if campaign["status"] not in ("running", "done"):
        raise CampaignError("진행 중인 캠페인만 순위를 입력할 수 있습니다.")
    campaign_model.upsert_daily(campaign["id"], day, rank)
    fields = {"rank_now": rank}
    if campaign["rank_start"] is None:
        fields["rank_start"] = rank
    campaign_model.update(campaign["id"], fields)
    return campaign_model.get(campaign["id"])


# ---- progress helpers (templates) -----------------------------------------
def progress(campaign, today=None):
    """관리 표 진행 셀용 {'total','elapsed','pct','label','sub','cls'}."""
    today = today or date.today()
    total = days_between(campaign["start_date"], campaign["end_date"])
    st = campaign["status"]
    if st == "pending":
        return {"cls": "wait", "pct": 0, "label": "등록 대기", "sub": f"{campaign['start_date']:%m.%d} 시작 예정", "total": total, "elapsed": 0}
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
