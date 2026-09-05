"""admin_log table — every admin write goes through log()."""
from ..db import execute, query


def log(admin_id, action, target_type=None, target_id=None, summary=None):
    return execute(
        "INSERT INTO admin_log (admin_id, action, target_type, target_id, summary) VALUES (%s,%s,%s,%s,%s)",
        [admin_id, action, target_type, target_id, (summary or "")[:300]])


def recent(limit=10):
    return query(
        """SELECT l.*, u.nickname AS admin_name FROM admin_log l LEFT JOIN users u ON u.id = l.admin_id
           ORDER BY l.created_at DESC, l.id DESC LIMIT %s""", [limit])


def list_admin(q=None, action=None, date_from=None, date_to=None, page=1, per_page=30):
    """로그 기록 화면용: 행위자 아이디 검색 + 구분 + 기간 필터."""
    from ..db import query_one
    where, params = ["1=1"], []
    if q:
        where.append("(u.username LIKE %s OR u.nickname LIKE %s)"); params += [f"%{q}%"] * 2
    if action:
        where.append("l.action = %s"); params.append(action)
    if date_from:
        where.append("l.created_at >= %s"); params.append(f"{date_from} 00:00:00")
    if date_to:
        where.append("l.created_at <= %s"); params.append(f"{date_to} 23:59:59")
    w = " AND ".join(where)
    rows = query(
        f"""SELECT l.*, u.username AS admin_username, u.nickname AS admin_name
            FROM admin_log l LEFT JOIN users u ON u.id = l.admin_id
            WHERE {w} ORDER BY l.created_at DESC, l.id DESC LIMIT %s OFFSET %s""",
        params + [per_page, (page - 1) * per_page])
    total = query_one(f"SELECT COUNT(*) AS n FROM admin_log l LEFT JOIN users u ON u.id = l.admin_id WHERE {w}", params)["n"]
    return rows, total


def distinct_actions():
    return [r["action"] for r in query("SELECT DISTINCT action FROM admin_log ORDER BY action")]
