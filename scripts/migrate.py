"""멱등 DB 마이그레이션 — 배포 때마다 실행 (scripts/deploy.sh).

반복 실행해도 안전하게, 없는 것만 적용한다. 트리플업(bbe_shop)은 신규 DB 로 시작하므로
현재 적용할 마이그레이션이 없다 — 스키마 변경이 생기면 여기에 추가.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymysql  # noqa: E402

from app.config import Config  # noqa: E402


def connect():
    return pymysql.connect(host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
                           password=Config.DB_PASSWORD, database=Config.DB_NAME,
                           charset="utf8mb4", autocommit=True)


def column_exists(cur, table, column):
    cur.execute(
        """SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
        (Config.DB_NAME, table, column))
    return cur.fetchone()[0] > 0


def main():
    conn = connect()
    cur = conn.cursor()
    applied = []
    # 예시:
    # if not column_exists(cur, "campaigns", "new_col"):
    #     cur.execute("ALTER TABLE campaigns ADD COLUMN new_col INT NULL")
    #     applied.append("campaigns.new_col")
    conn.close()
    print("migrate:", ", ".join(applied) if applied else "적용할 항목 없음")


if __name__ == "__main__":
    main()
