"""순위 서버(rankserver) 파트너 API 클라이언트.

프로젝트 관례(naver_ad.py)대로 urllib 사용. 네트워크 실패가 캠페인 등록을 막지 않도록
예외를 던지지 않고 {"error": ...} 를 반환한다 — 호출측은 track_status 로만 기록.
"""
import json
import logging
import urllib.error
import urllib.request

from flask import current_app

log = logging.getLogger(__name__)


def _call(method, path, payload=None):
    cfg = current_app.config
    url = cfg["RANK_SERVER_URL"].rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "X-NSR-Token": cfg["RANK_API_TOKEN"]})
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("RANK_TIMEOUT", 10)) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        log.warning("rank server %s %s -> HTTP %s %s", method, path, e.code, body)
        return {"error": f"HTTP {e.code}", "detail": body}
    except Exception as e:
        log.warning("rank server %s %s 실패: %s", method, path, e)
        return {"error": str(e)}


def track(keyword, url, product_name=None):
    """추적 등록. 성공: {ok, trackId, status, rank(오늘 수집분 있으면), prodNm, date}"""
    return _call("POST", "/partner/slots", {"keyword": keyword, "url": url, "productName": product_name})


def untrack(track_id):
    return _call("DELETE", f"/partner/slots/{int(track_id)}")


def fetch_ranks(track_id):
    """이력 조회 (콜백 유실 시 폴백). 성공: {ok, prodNm, ranks: [{date, rank}]}"""
    return _call("GET", f"/partner/slots/{int(track_id)}/ranks")
