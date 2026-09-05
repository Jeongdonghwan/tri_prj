-- 트리플업 (bbe_shop) 스키마 — MariaDB 10.6, utf8mb4.
-- bbe_prj 에서 공지사항 + 쇼핑캠페인만 발췌. 결제/커뮤니티/인기트래픽/배너/대행 테이블 없음.
-- 순위 데이터는 rankserver 파트너 API 경유 — 이 DB 에는 campaigns.track_id 매핑만 둔다.

CREATE DATABASE IF NOT EXISTS bbe_shop CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE bbe_shop;

SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------------- users (관리자 발급형 계정 — 회원가입 없음)
CREATE TABLE IF NOT EXISTS users (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  username        VARCHAR(50) NOT NULL UNIQUE,
  password_hash   VARCHAR(255) NOT NULL,
  nickname        VARCHAR(30) NOT NULL,
  role            ENUM('user','admin') NOT NULL DEFAULT 'user',
  company         VARCHAR(100) NULL,
  memo            VARCHAR(255) NULL,
  status          ENUM('active','suspended') NOT NULL DEFAULT 'active',
  last_login_at   DATETIME NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------------- media / campaigns
CREATE TABLE IF NOT EXISTS media (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  channel           ENUM('store') NOT NULL DEFAULT 'store',
  group_name        VARCHAR(40) NOT NULL DEFAULT '',
  name              VARCHAR(40) NOT NULL,
  tagline           VARCHAR(80) NULL,
  logo_url          VARCHAR(255) NULL,
  color             CHAR(7) NOT NULL DEFAULT '#4B5563',
  unit_price        INT NOT NULL,
  list_price        INT NULL,
  min_days          INT NOT NULL DEFAULT 3,
  min_daily         INT NOT NULL DEFAULT 50,
  max_daily         INT NOT NULL DEFAULT 500,
  efficiency_auto   TINYINT NOT NULL DEFAULT 0,
  efficiency_manual TINYINT NULL,
  cutoff_time       TIME NOT NULL DEFAULT '13:30:00',
  same_day          TINYINT(1) NOT NULL DEFAULT 1,
  description       TEXT NULL,
  badge             ENUM('rec','best','new') NULL,
  eff_level         ENUM('normal','good','best') NOT NULL DEFAULT 'good',
  eff_note          VARCHAR(120) NULL,
  sort              INT NOT NULL DEFAULT 0,
  is_active         TINYINT(1) NOT NULL DEFAULT 1,
  INDEX idx_media_channel (channel, is_active, sort)
) ENGINE=InnoDB;

-- 등록 즉시 running. track_id = rankserver 슬롯 id (콜백 매핑 키).
CREATE TABLE IF NOT EXISTS campaigns (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  order_no         CHAR(10) NOT NULL UNIQUE,
  user_id          INT NOT NULL,
  channel          ENUM('store') NOT NULL DEFAULT 'store',
  media_id         INT NOT NULL,
  status           ENUM('running','done','stopped') NOT NULL DEFAULT 'running',
  biz_name         VARCHAR(80) NOT NULL,
  product_name     VARCHAR(120) NULL,
  target_url       VARCHAR(500) NOT NULL,
  main_keyword     VARCHAR(60) NOT NULL,
  sub_keywords     JSON NULL,
  setting_keywords JSON NULL,
  keyword_mode     ENUM('ai','manual') NOT NULL DEFAULT 'ai',
  extra            JSON NULL,
  start_date       DATE NOT NULL,
  end_date         DATE NOT NULL,
  daily_qty        INT NOT NULL,
  total_qty        INT NOT NULL,
  unit_price       INT NOT NULL,
  discount         INT NOT NULL DEFAULT 0,
  vat              INT NOT NULL DEFAULT 0,
  paid_amount      INT NOT NULL DEFAULT 0,
  pay_method       ENUM('card','bank') NOT NULL DEFAULT 'card',
  paid_at          DATETIME NULL,
  refund_amount    INT NOT NULL DEFAULT 0,
  warn_words       VARCHAR(300) NULL,
  rank_start       INT NULL,
  rank_now         INT NULL,
  track_id         INT NULL,
  track_status     VARCHAR(20) NULL,
  admin_memo       TEXT NULL,
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_campaign_user (user_id, channel, status),
  INDEX idx_campaign_status (status, created_at),
  INDEX idx_campaign_track (track_id, status),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (media_id) REFERENCES media(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS campaign_daily (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  campaign_id INT NOT NULL,
  date        DATE NOT NULL,
  done_qty    INT NOT NULL DEFAULT 0,
  rank        INT NULL,
  UNIQUE KEY uq_campaign_daily (campaign_id, date),
  FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS status_log (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  campaign_id INT NOT NULL,
  from_status VARCHAR(12) NULL,
  to_status   VARCHAR(12) NOT NULL,
  actor_id    INT NULL,
  memo        VARCHAR(300) NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_status_log_campaign (campaign_id, created_at),
  FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS forbidden_words (
  id       INT AUTO_INCREMENT PRIMARY KEY,
  word     VARCHAR(60) NOT NULL,
  channel  ENUM('store') NULL,
  severity ENUM('warn','block') NOT NULL DEFAULT 'warn'
) ENGINE=InnoDB;

-- 활동 로그 (로그인 · 계정 발급/수정 · 캠페인 처리 · 콘텐츠/매체 관리) — /admin/logs 화면
CREATE TABLE IF NOT EXISTS admin_log (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  admin_id    INT NOT NULL,
  action      VARCHAR(40) NOT NULL,
  target_type VARCHAR(30) NULL,
  target_id   INT NULL,
  summary     VARCHAR(300) NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_admin_log_created (created_at),
  INDEX idx_admin_log_actor (admin_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS settings (
  k          VARCHAR(40) PRIMARY KEY,
  v          VARCHAR(500) NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------------- contents / notifications
CREATE TABLE IF NOT EXISTS contents (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  board          ENUM('notice','info','series') NOT NULL DEFAULT 'notice',
  channel        ENUM('store') NULL,
  category       VARCHAR(20) NULL,
  series_no      INT NULL,
  title          VARCHAR(200) NOT NULL,
  body           MEDIUMTEXT NULL,
  status         ENUM('draft','scheduled','published') NOT NULL DEFAULT 'published',
  publish_at     DATETIME NULL,
  is_pinned      TINYINT(1) NOT NULL DEFAULT 0,
  show_dashboard TINYINT(1) NOT NULL DEFAULT 1,
  notify         TINYINT(1) NOT NULL DEFAULT 0,
  views          INT NOT NULL DEFAULT 0,
  author_id      INT NULL,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_contents_board (board, status, is_pinned, publish_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS notifications (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  user_id    INT NOT NULL,
  type       VARCHAR(30) NOT NULL,
  title      VARCHAR(200) NOT NULL,
  link       VARCHAR(300) NULL,
  is_read    TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_notifications_user (user_id, is_read, created_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------- 쇼핑 작업량 권장 체크 / 키워드 도구
CREATE TABLE IF NOT EXISTS store_slots (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  user_id     INT NOT NULL,
  keyword     VARCHAR(60) NOT NULL,
  product_url VARCHAR(500) NULL,
  store_name  VARCHAR(80) NULL,
  pc_cnt      INT NOT NULL DEFAULT 0,
  mo_cnt      INT NOT NULL DEFAULT 0,
  reco_qty    INT NOT NULL DEFAULT 1,
  fetched_at  DATETIME NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_store_slots_user (user_id),
  FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS slot_daily (
  slot_id    INT NOT NULL,
  date       DATE NOT NULL,
  rank_total INT NULL,
  rank_price INT NULL,
  PRIMARY KEY (slot_id, date),
  FOREIGN KEY (slot_id) REFERENCES store_slots(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS keyword_cache (
  keyword    VARCHAR(60) PRIMARY KEY,
  pc_cnt     INT NOT NULL DEFAULT 0,
  mo_cnt     INT NOT NULL DEFAULT 0,
  comp       VARCHAR(10) NULL,
  fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS related_cache (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  seed       VARCHAR(60) NOT NULL,
  keyword    VARCHAR(60) NOT NULL,
  pc_cnt     INT NOT NULL DEFAULT 0,
  mo_cnt     INT NOT NULL DEFAULT 0,
  fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_related_seed (seed)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS keyword_query_log (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  user_id    INT NULL,
  ip         VARCHAR(45) NOT NULL,
  tool       VARCHAR(20) NOT NULL,
  query      VARCHAR(300) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_kql_user (user_id, created_at),
  INDEX idx_kql_ip (ip, created_at)
) ENGINE=InnoDB;

SET FOREIGN_KEY_CHECKS = 1;
