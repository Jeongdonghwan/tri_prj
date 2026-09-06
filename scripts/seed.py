"""개발용 시드 데이터.

    python scripts/seed.py            # truncate + 시드 입력
    python scripts/seed.py --schema   # schema.sql 먼저 적용
    python scripts/seed.py --reset    # DB DROP 후 재생성 + 시드 (개발 전용)

계정: admin / admin1234!  (관리자),  demo / demo1234!  (일반)
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pymysql
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402


def connect(database=None):
    return pymysql.connect(
        host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
        password=Config.DB_PASSWORD, database=database, charset="utf8mb4", autocommit=True,
    )


def apply_schema(reset=False):
    raw = (ROOT / "schema.sql").read_text(encoding="utf-8")
    if Config.DB_NAME != "bbe_shop":
        raw = raw.replace("bbe_shop", Config.DB_NAME)  # schema.sql 은 기본 DB명을 하드코딩
    sql = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("--"))
    conn = connect()
    with conn.cursor() as cur:
        if reset:
            cur.execute(f"DROP DATABASE IF EXISTS {Config.DB_NAME}")
        for stmt in sql.split(";"):
            s = stmt.strip()
            if s:
                cur.execute(s)
    conn.close()
    print("schema applied")


def para(*ps):
    return "".join(f"<p>{p}</p>" for p in ps)


MEDIA = [
    ("스토어A", "리워드", "#7C3AED", 160, "rec", 80),
    ("스토어B", "리워드", "#0891B2", 155, "best", 76),
    ("스토어C", "유입", "#2563EB", 110, None, 70),
    ("스토어D", "유입", "#F59E0B", 115, "new", 64),
    ("스토어E", "복합", "#F97316", 90, None, 59),
]

FORBIDDEN = [
    ("최저가", None, "block"), ("1위", None, "warn"), ("업계 최고", None, "warn"), ("100% 보장", None, "block"),
    ("무조건", None, "warn"), ("전국 1등", None, "warn"), ("정품 보장", "store", "warn"),
    ("공식 파트너", None, "warn"), ("네이버 공식", None, "block"), ("절대", None, "warn"),
]

NOTICES = [
    ("update", "트리플업 오픈 안내", 1),
    ("update", "캠페인 등록 시 순위 추적이 자동으로 시작됩니다", 0),
    ("guide", "쇼핑 캠페인 등록 가이드", 0),
]


def seed():
    conn = connect(Config.DB_NAME)
    cur = conn.cursor()
    now = datetime.now()

    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    for t in ("contents", "media", "forbidden_words", "admin_log", "campaign_daily", "status_log",
              "campaigns", "settings", "notifications", "users"):
        cur.execute(f"TRUNCATE TABLE {t}")

    # 계정 (관리자 발급형 — 회원가입 없음)
    cur.executemany(
        "INSERT INTO users (username, password_hash, nickname, role, company) VALUES (%s,%s,%s,%s,%s)",
        [("admin", generate_password_hash("admin1234!"), "운영팀", "admin", "트리플업"),
         ("demo", generate_password_hash("demo1234!"), "데모계정", "user", "데모상사")],
    )
    admin_id = 1

    # 매체
    cur.executemany(
        """INSERT INTO media (channel, group_name, name, color, unit_price, min_days, min_daily, max_daily,
           efficiency_auto, badge, eff_level, sort)
           VALUES ('store',%s,%s,%s,%s,3,50,500,%s,%s,%s,%s)""",
        [(grp, name, color, price, eff, badge, "best" if eff >= 75 else "good", i)
         for i, (name, grp, color, price, badge, eff) in enumerate(MEDIA)])

    # 공지
    cur.executemany(
        """INSERT INTO contents (board, category, title, body, publish_at, is_pinned, author_id, status)
           VALUES ('notice',%s,%s,%s,%s,%s,%s,'published')""",
        [(cat, title, para(f"<b>{title}</b>", "운영팀에서 안내드립니다."), now - timedelta(days=i + 1), pinned, admin_id)
         for i, (cat, title, pinned) in enumerate(NOTICES)])

    # 금칙어 / 설정
    cur.executemany("INSERT INTO forbidden_words (word, channel, severity) VALUES (%s,%s,%s)", FORBIDDEN)
    cur.executemany("INSERT INTO settings (k, v) VALUES (%s,%s)",
                    [("strip_on", "0"), ("strip_text", ""), ("strip_link", ""), ("strip_bg", "#2563EB")])

    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.close()
    print(f"seed done: users 2 (admin/demo), media {len(MEDIA)}, notices {len(NOTICES)}, forbidden {len(FORBIDDEN)}")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        apply_schema(reset=True)
    elif "--schema" in sys.argv:
        apply_schema()
    seed()
