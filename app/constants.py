"""Business constants shared across phases. (No point/prepaid concept — campaigns are paid per order via PG.)"""

# Member tier — assigned by operators (agency cert approval sets 'agency'; 'master' is manual).

# Campaign order discount — disabled 2026-08-31 (coupons/discounts may return later)
DISCOUNT_RULES = []
VAT_RATE = 0.10

MEDIA_SECTIONS = ["리워드", "유입", "복합"]

CHANNEL_LABEL = {"store": "쇼핑·스토어"}
CHANNEL_CLASS = {"store": "c-store"}
STATUS_LABEL = {"pay_wait": "결제 대기", "review": "검수", "approved": "승인", "running": "진행",
                "rejected": "반려", "done": "완료", "stopped": "중단", "cancelled": "취소"}
STATUS_CLASS = {"pay_wait": "s-wait", "review": "s-review", "approved": "s-appr", "running": "s-run",
                "rejected": "s-rej", "done": "s-done", "stopped": "s-stop", "cancelled": "s-wait"}
STATUS_ORDER = ["pay_wait", "review", "approved", "running", "rejected", "done", "stopped", "cancelled"]

# Campaign status transition table (from -> allowed to).
# 결제 플로우 제거: 등록 즉시 running. (과거 상태 라벨은 표시용으로 유지)
TRANSITIONS = {
    "running": {"done", "stopped"},
}

CUTOFF_TIME = "13:30"
DATE_PRESETS = [3, 5, 7, 10, 14]

# Store tracking slots (2-4-1)
STORE_SLOT_MAX = 10
RECO_PER_1000 = 1.5

# Link whitelist per channel (host suffix match)
URL_WHITELIST = {
    "store": ["smartstore.naver.com", "brand.naver.com", "shopping.naver.com", "m.smartstore.naver.com"],
}



def reco_qty(monthly_volume):
    """Recommended daily qty for store slots: 1.5 per 1,000 daily searches, min 1."""
    return max(1, round(monthly_volume / 30 / 1000 * RECO_PER_1000))
