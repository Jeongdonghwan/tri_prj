"""campaigns / campaign_daily / status_log tables. Status changes only via services.campaign_service.transition."""
import json

from ..db import execute, query, query_one

ACTIVE_STATUSES = ("pending", "running")

SELECT = """SELECT c.*, m.name AS media_name, m.color AS media_color, m.logo_url AS media_logo, m.min_days, m.min_daily, m.max_daily
            FROM campaigns c JOIN media m ON m.id = c.media_id"""


def _decode(row):
    if row:
        for k in ("setting_keywords",):
            v = row.get(k)
            if isinstance(v, str):
                try:
                    row[k] = json.loads(v)
                except ValueError:
                    row[k] = None
    return row


def get(campaign_id):
    return _decode(query_one(f"{SELECT} WHERE c.id = %s", [campaign_id]))


def max_slot_no(user_id):
    row = query_one("SELECT COALESCE(MAX(slot_no), 0) AS n FROM campaigns WHERE user_id = %s", [user_id])
    return int(row["n"])


def insert(data):
    cols = ", ".join(data)
    ph = ", ".join(["%s"] * len(data))
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for v in data.values()]
    return execute(f"INSERT INTO campaigns ({cols}) VALUES ({ph})", vals)


def update(campaign_id, data):
    sets = ", ".join(f"{k} = %s" for k in data)
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for v in data.values()]
    execute(f"UPDATE campaigns SET {sets} WHERE id = %s", [*vals, campaign_id])


def set_status(campaign_id, status):
    """Only campaign_service.transition may call this."""
    execute("UPDATE campaigns SET status = %s WHERE id = %s", [status, campaign_id])


# ---- lists ---------------------------------------------------------------
def _filters(user_id, channel, status, period, media_id, q):
    where, params = ["c.user_id = %s", "c.channel = %s"], [user_id, channel]
    if status:
        where.append("c.status = %s"); params.append(status)
    if period == "month":
        where.append("c.created_at >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01')")
    elif period == "last":
        where.append("c.created_at >= DATE_FORMAT(CURDATE() - INTERVAL 1 MONTH, '%%Y-%%m-01') AND c.created_at < DATE_FORMAT(CURDATE(), '%%Y-%%m-01')")
    if media_id:
        where.append("c.media_id = %s"); params.append(media_id)
    if q:
        if q.isdigit():
            where.append("(c.slot_no = %s OR c.main_keyword LIKE %s OR c.product_name LIKE %s)")
            params += [int(q), f"%{q}%", f"%{q}%"]
        else:
            where.append("(c.main_keyword LIKE %s OR c.product_name LIKE %s)")
            params += [f"%{q}%"] * 2
    return " AND ".join(where), params


def list_user(user_id, channel, status=None, period=None, media_id=None, q=None, page=1, per_page=20):
    where, params = _filters(user_id, channel, status, period, media_id, q)
    rows = query(f"{SELECT} WHERE {where} ORDER BY c.slot_no ASC, c.id ASC LIMIT %s OFFSET %s",
                 params + [per_page, (page - 1) * per_page])
    return [_decode(r) for r in rows]


def count_user(user_id, channel, status=None, period=None, media_id=None, q=None):
    where, params = _filters(user_id, channel, status, period, media_id, q)
    return query_one(f"SELECT COUNT(*) AS n FROM campaigns c WHERE {where}", params)["n"]


def status_counts(user_id, channel):
    rows = query("SELECT status, COUNT(*) AS n FROM campaigns WHERE user_id = %s AND channel = %s GROUP BY status",
                 [user_id, channel])
    return {r["status"]: r["n"] for r in rows}


def media_used(user_id, channel):
    return query(
        """SELECT DISTINCT m.id, m.name FROM campaigns c JOIN media m ON m.id = c.media_id
           WHERE c.user_id = %s AND c.channel = %s ORDER BY m.name""", [user_id, channel])


def list_recent_channel(user_id, channel, limit=5):
    ph = ",".join(["%s"] * len(ACTIVE_STATUSES))
    return [_decode(r) for r in query(
        f"{SELECT} WHERE c.user_id = %s AND c.channel = %s AND c.status IN ({ph}) ORDER BY c.created_at DESC LIMIT %s",
        [user_id, channel, *ACTIVE_STATUSES, limit])]


# ---- summaries -----------------------------------------------------------
def summary_by_channel(user_id):
    rows = query("SELECT channel, status, COUNT(*) AS n FROM campaigns WHERE user_id = %s GROUP BY channel, status", [user_id])
    out = {}
    for r in rows:
        out.setdefault(r["channel"], {})[r["status"]] = r["n"]
    return out


def count_done(user_id):
    return query_one("SELECT COUNT(*) AS n FROM campaigns WHERE user_id = %s AND status = 'done'", [user_id])["n"]


def count_active(user_id):
    ph = ",".join(["%s"] * len(ACTIVE_STATUSES))
    return query_one(f"SELECT COUNT(*) AS n FROM campaigns WHERE user_id = %s AND status IN ({ph})", [user_id, *ACTIVE_STATUSES])["n"]


def avg_rank_change(user_id, channel):
    row = query_one(
        """SELECT AVG(rank_start - rank_now) AS avg_up, COUNT(*) AS n FROM campaigns
           WHERE user_id = %s AND channel = %s AND status = 'done' AND rank_start IS NOT NULL AND rank_now IS NOT NULL""",
        [user_id, channel])
    return (float(row["avg_up"]) if row["avg_up"] is not None else None), row["n"]


# ---- campaign_daily ------------------------------------------------------
def upsert_daily(campaign_id, date, rank, done_qty):
    execute(
        """INSERT INTO campaign_daily (campaign_id, date, rank, done_qty) VALUES (%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE rank = VALUES(rank), done_qty = VALUES(done_qty)""",
        [campaign_id, date, rank, done_qty])


def list_daily(campaign_id):
    return query("SELECT * FROM campaign_daily WHERE campaign_id = %s ORDER BY date", [campaign_id])


def total_done_qty(campaign_id):
    return int(query_one("SELECT COALESCE(SUM(done_qty), 0) AS n FROM campaign_daily WHERE campaign_id = %s", [campaign_id])["n"])


# ---- 사용자 활동 로그 (본인 슬롯 이력 + 로그인 기록) ------------------------
def user_logs(user_id, date_from=None, date_to=None, page=1, per_page=30):
    where, params = [], []
    if date_from:
        where.append("t.created_at >= %s"); params.append(f"{date_from} 00:00:00")
    if date_to:
        where.append("t.created_at <= %s"); params.append(f"{date_to} 23:59:59")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    inner = """
        SELECT l.created_at, 'campaign' AS kind, c.slot_no, l.to_status, l.memo
        FROM status_log l JOIN campaigns c ON c.id = l.campaign_id WHERE c.user_id = %s
        UNION ALL
        SELECT a.created_at, 'login', NULL, NULL, NULL
        FROM admin_log a WHERE a.admin_id = %s AND a.action = 'login'"""
    rows = query(f"SELECT * FROM ({inner}) t {w} ORDER BY t.created_at DESC LIMIT %s OFFSET %s",
                 [user_id, user_id, *params, per_page, (page - 1) * per_page])
    total = query_one(f"SELECT COUNT(*) AS n FROM ({inner}) t {w}", [user_id, user_id, *params])["n"]
    return rows, total


# ---- status_log ----------------------------------------------------------
def add_log(campaign_id, from_status, to_status, actor_id=None, memo=None):
    return execute(
        "INSERT INTO status_log (campaign_id, from_status, to_status, actor_id, memo) VALUES (%s,%s,%s,%s,%s)",
        [campaign_id, from_status, to_status, actor_id, memo])


def list_log(campaign_id):
    return query("SELECT * FROM status_log WHERE campaign_id = %s ORDER BY created_at DESC, id DESC", [campaign_id])


# ---- admin ---------------------------------------------------------------
ADMIN_SELECT = """SELECT c.*, m.name AS media_name, m.color AS media_color, u.nickname, u.username AS user_username
                  FROM campaigns c JOIN media m ON m.id = c.media_id JOIN users u ON u.id = c.user_id"""


def _admin_filters(status, channel, media_id, period, q):
    where, params = ["1=1"], []
    if status:
        where.append("c.status = %s"); params.append(status)
    if channel:
        where.append("c.channel = %s"); params.append(channel)
    if media_id:
        where.append("c.media_id = %s"); params.append(media_id)
    if period == "today":
        where.append("c.created_at >= CURDATE()")
    elif period == "week":
        where.append("c.created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)")
    elif period == "month":
        where.append("c.created_at >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01')")
    if q:
        where.append("(u.username LIKE %s OR u.nickname LIKE %s OR c.main_keyword LIKE %s OR c.product_name LIKE %s)")
        params += [f"%{q}%"] * 4
    return " AND ".join(where), params


def admin_list(status=None, channel=None, media_id=None, period=None, q=None, page=1, per_page=20):
    w, p = _admin_filters(status, channel, media_id, period, q)
    rows = query(f"{ADMIN_SELECT} WHERE {w} ORDER BY c.created_at DESC, c.id DESC LIMIT %s OFFSET %s", p + [per_page, (page - 1) * per_page])
    return [_decode(r) for r in rows]


def admin_all(status=None, channel=None, media_id=None, period=None, q=None, limit=5000):
    w, p = _admin_filters(status, channel, media_id, period, q)
    return [_decode(r) for r in query(f"{ADMIN_SELECT} WHERE {w} ORDER BY c.created_at DESC LIMIT %s", p + [limit])]


def admin_count(status=None, channel=None, media_id=None, period=None, q=None):
    w, p = _admin_filters(status, channel, media_id, period, q)
    return query_one(f"SELECT COUNT(*) AS n FROM campaigns c JOIN users u ON u.id = c.user_id WHERE {w}", p)["n"]


def admin_status_counts():
    return {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) AS n FROM campaigns GROUP BY status")}


def running_without_today_rank():
    row = query_one(
        """SELECT COUNT(*) AS n FROM campaigns c WHERE c.status = 'running'
           AND NOT EXISTS (SELECT 1 FROM campaign_daily d WHERE d.campaign_id = c.id AND d.date = CURDATE())""")
    return row["n"]


def today_intake():
    return query_one("SELECT COUNT(*) AS n FROM campaigns WHERE created_at >= CURDATE()")


def today_intake_by_media(limit=5):
    return query(
        """SELECT m.name, COUNT(*) AS n FROM campaigns c JOIN media m ON m.id = c.media_id
           WHERE c.created_at >= CURDATE() GROUP BY m.id ORDER BY n DESC LIMIT %s""", [limit])


def today_rank(campaign_id):
    return query_one("SELECT rank, done_qty FROM campaign_daily WHERE campaign_id = %s AND date = CURDATE()", [campaign_id])


def list_by_user(user_id, limit=20):
    return [_decode(r) for r in query(f"{SELECT} WHERE c.user_id = %s ORDER BY c.created_at DESC LIMIT %s", [user_id, limit])]


def set_admin_memo(campaign_id, memo):
    execute("UPDATE campaigns SET admin_memo = %s WHERE id = %s", [memo or None, campaign_id])


def done_rank_stats(media_id, days=30):
    row = query_one(
        """SELECT COUNT(*) AS n, SUM(rank_start IS NOT NULL AND rank_now IS NOT NULL AND rank_now < rank_start) AS up
           FROM campaigns WHERE media_id = %s AND status = 'done' AND updated_at >= DATE_SUB(NOW(), INTERVAL %s DAY)""", [media_id, days])
    return row["n"], int(row["up"] or 0)
