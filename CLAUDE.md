# CLAUDE.md

## 프로젝트 — 트리플업 (bbe_shop)
bbe_prj 에서 **공지사항 + 쇼핑캠페인 관리**만 발췌해 만든 내부용 사이트.
캠페인을 등록하면 rankserver(마케팅광장 순위 배치 서버) 파트너 API 로 순위 추적이 **자동으로 시작**되고,
매일 배치(11:00/17:00)에서 갱신된 순위가 콜백으로 들어온다. 결제·커뮤니티·인기트래픽·쿠팡/플레이스 채널 없음.

- 사이트명: **트리플업** (로고 `app/static/img/logo-tripleup.svg`)
- **전체 화면 로그인 필수** (`app/__init__.py` `_force_login`). 예외: /auth/*, /static/*, /api/rank/callback
- **회원가입 없음** — 관리자가 /admin/users 에서 계정 발급 (Malon_Project 방식: 아이디/비번/권한/회사/메모)
- 로그 기록: 로그인·계정 발급/수정·캠페인 처리 전부 admin_log → /admin/logs 화면
- 디자인: 다크 네이비 라운드 사이드바 + 라임 액센트 + 라벤더 배경 (`css/theme-tripleup.css` 오버라이드)

## 스택
- Python 3.11+, Flask 3, Jinja2 SSR, pymysql(raw SQL, ORM 금지), MariaDB 10.6, 바닐라 JS
- SQL 은 app/models/ 함수로만. CSS 는 tokens.css 변수 + theme-tripleup.css 오버라이드. 아이콘은 Lucide.

## 순위 연동 (rankserver)
- `services/rank_client.py`: track/untrack/fetch_ranks — urllib, 실패 시 {"error"} 반환(등록을 막지 않음)
- `blueprints/rank_api.py`: `POST /api/rank/callback` {trackId, date, rank, prodNm} 수신 → 같은 track_id 의 running/done 캠페인 전부 record_rank
- `campaigns.track_id` = rankserver slot id (N:1 공유 가능). 캠페인 중단 시 같은 track_id 의 다른 running 캠페인이 없을 때만 untrack
- 등록 응답 status=collected(캐시 히트)면 즉시 오늘 순위 기록
- .env: RANK_SERVER_URL / RANK_API_TOKEN(=rankserver NSR_PARTNER_TOKEN) / RANK_CALLBACK_TOKEN
- 폴백: 순위표(ranks) 열람 시 오늘 순위 없고 5분 경과면 fetch_ranks 로 보정

## 상태 모델
`running → done | stopped` 만. 등록 = 즉시 running (결제 플로우 없음).
상태 변경은 campaign_service.transition()/stop() 외 경로 금지 (status_log 기록).

## 규칙
- 관리자 쓰기 + 로그인은 admin_log 에 기록 (`_log()` / auth.\_login)
- 목록 페이지는 pagination 매크로, 페이지당 20
- 새 라우트는 app/__init__.py MENU 상수와 동기화
- 한글 UI. 주석은 한글 허용.

## 실행
cp .env.example .env → python scripts/seed.py --schema → flask run
- 시드 계정: admin/admin1234!, demo/demo1234! (개발용, 운영 배포 시 반드시 변경)
- 개발 로그인: /auth/dev-login?as=admin|user (DEV_LOGIN=1 + FLASK_DEBUG=1)

## 로컬 E2E (rankserver 연동)
로컬 rankserver(:5010, NSR_PARTNER_TOKEN=partnertoken-dev, 콜백 → :8035/api/rank/callback) + 이 앱을 8035 포트로 실행.
등록 → nsr_job 긴급(priority 10) 생성 → 수집 완료 → 콜백 → campaign_daily 기록 → 재등록 시 캐시 히트 즉시 순위.
