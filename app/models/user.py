"""users 테이블 — 관리자 발급형 계정 (회원가입 없음, 아이디/비밀번호 로그인)."""
from ..db import execute, query, query_one


def get_by_id(user_id):
    return query_one("SELECT * FROM users WHERE id = %s", [user_id])


def get_by_username(username):
    return query_one("SELECT * FROM users WHERE username = %s", [username])


def create(username, password_hash, nickname=None, role="user", company=None, memo=None):
    return execute(
        "INSERT INTO users (username, password_hash, nickname, role, company, memo) VALUES (%s,%s,%s,%s,%s,%s)",
        [username, password_hash, nickname or username, role, company or None, memo or None])


def update_account(user_id, nickname, role, company, memo):
    execute("UPDATE users SET nickname = %s, role = %s, company = %s, memo = %s WHERE id = %s",
            [nickname, role, company or None, memo or None, user_id])


def set_password(user_id, password_hash):
    execute("UPDATE users SET password_hash = %s WHERE id = %s", [password_hash, user_id])


def set_status(user_id, status):
    execute("UPDATE users SET status = %s WHERE id = %s", [status, user_id])


def touch_login(user_id):
    execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", [user_id])


# ---- admin ---------------------------------------------------------------
def list_admin(q=None, status=None, page=1, per_page=20):
    where, params = ["1=1"], []
    if q:
        where.append("(username LIKE %s OR nickname LIKE %s OR company LIKE %s)"); params += [f"%{q}%"] * 3
    if status:
        where.append("status = %s"); params.append(status)
    w = " AND ".join(where)
    rows = query(
        f"""SELECT u.*, (SELECT COUNT(*) FROM campaigns c WHERE c.user_id = u.id) AS campaign_cnt,
                   (SELECT COUNT(*) FROM campaigns c WHERE c.user_id = u.id AND c.status = 'running') AS running_cnt
            FROM users u WHERE {w} ORDER BY u.created_at DESC, u.id DESC LIMIT %s OFFSET %s""",
        params + [per_page, (page - 1) * per_page])
    total = query_one(f"SELECT COUNT(*) AS n FROM users WHERE {w}", params)["n"]
    return rows, total


def count_by_status():
    return {r["status"]: r["n"] for r in query("SELECT status, COUNT(*) AS n FROM users GROUP BY status")}
