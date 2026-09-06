"""공용 비즈니스 상수. 결제·금액 개념 없음 — 캠페인은 어드민이 발급하고 사용자는 내용만 등록한다."""

CHANNEL_LABEL = {"store": "쇼핑·스토어"}
CHANNEL_CLASS = {"store": "c-store"}

# pending = 어드민이 발급한 빈 캠페인(등록 대기). 사용자가 키워드·상품을 등록하면 running.
STATUS_LABEL = {"pending": "등록 대기", "running": "정상", "done": "완료", "stopped": "중단"}
STATUS_CLASS = {"pending": "s-wait", "running": "s-run", "done": "s-done", "stopped": "s-stop"}
STATUS_ORDER = ["pending", "running", "done", "stopped"]

# 상태 전이표 (from -> allowed to). 변경은 campaign_service.transition() 으로만.
TRANSITIONS = {
    "pending": {"running"},
    "running": {"done", "stopped"},
}

# 링크 화이트리스트 (호스트 접미 일치)
URL_WHITELIST = {
    "store": ["smartstore.naver.com", "brand.naver.com", "shopping.naver.com", "m.smartstore.naver.com"],
}
