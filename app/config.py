"""Application configuration loaded from .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "bbe_shop")
    DB_POOL_SIZE = 5

    # Service name is managed in exactly one place (spec 0).
    APP_NAME = os.getenv("APP_NAME", "트리플업")

    PER_PAGE = 20

    # Dev bypass login (/auth/dev-login). Off by default — set DEV_LOGIN=1 (+ FLASK_DEBUG=1) to enable.
    DEV_LOGIN = os.getenv("DEV_LOGIN", "0") == "1"


    # 순위 서버 연동 (rankserver 파트너 API)
    RANK_SERVER_URL = os.getenv("RANK_SERVER_URL", "http://127.0.0.1:5010")
    RANK_API_TOKEN = os.getenv("RANK_API_TOKEN", "")            # rankserver 의 NSR_PARTNER_TOKEN 과 동일
    RANK_CALLBACK_TOKEN = os.getenv("RANK_CALLBACK_TOKEN", "")  # 콜백 수신 검증용 (같은 값 공용 권장)
    RANK_TIMEOUT = 10

    # Naver Search Ad API (P4-c). Empty -> deterministic dummy data.
    NAVER_AD_ACCESS_LICENSE = os.getenv("NAVER_AD_ACCESS_LICENSE", "")
    NAVER_AD_SECRET_KEY = os.getenv("NAVER_AD_SECRET_KEY", "")
    NAVER_AD_CUSTOMER_ID = os.getenv("NAVER_AD_CUSTOMER_ID", "")
