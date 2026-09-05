"""순위 서버 콜백 수신: 수집 완료 시 rankserver 가 POST 하는 순위를 캠페인에 기록한다."""
import logging
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from ..db import query
from ..services import campaign_service
from ..models import campaign as campaign_model

log = logging.getLogger(__name__)
bp = Blueprint("rank_api", __name__)


@bp.post("/api/rank/callback")
def rank_callback():
    """{trackId, date, rank, prodNm} — 같은 track_id 를 쓰는 running 캠페인 전부에 기록."""
    token = current_app.config.get("RANK_CALLBACK_TOKEN")
    if not token or request.headers.get("X-NSR-Token") != token:
        return jsonify({"ok": False, "message": "인증 실패"}), 401
    body = request.get_json(silent=True) or {}
    track_id, day_s, rank = body.get("trackId"), body.get("date"), body.get("rank")
    if not track_id or not day_s:
        return jsonify({"ok": False, "message": "trackId/date 필요"}), 400
    try:
        day = datetime.strptime(day_s, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"ok": False, "message": "date 형식(YYYY-MM-DD)"}), 400

    rows = query("SELECT * FROM campaigns WHERE track_id = %s AND status IN ('running','done')", (track_id,))
    saved = 0
    for c in rows:
        try:
            done_qty = c["daily_qty"] if c["start_date"] <= day <= c["end_date"] else 0
            campaign_service.record_rank(c, day, rank, done_qty)
            if body.get("prodNm") and not c.get("product_name"):
                campaign_model.update(c["id"], {"product_name": body["prodNm"][:120]})
            saved += 1
        except campaign_service.CampaignError as e:   # 중단된 캠페인 등 — 무시
            log.info("콜백 기록 생략 campaign#%s: %s", c["id"], e)
        except Exception:
            log.exception("콜백 기록 실패 campaign#%s", c["id"])
    log.info("순위 콜백 track#%s %s rank=%s → 캠페인 %d건 기록", track_id, day_s, rank, saved)
    return jsonify({"ok": True, "saved": saved})
