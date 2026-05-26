-- ── 초기 스키마 (신규 DB 설치용) ──────────────────────────────────────────────
-- refactor/db-interest-schema: user_interests를 하트 토픽 저장 중심으로 단순화
-- 1. 확장 및 ENUM 타입 정의
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TYPE log_status AS ENUM ('pending', 'processed', 'archived');
CREATE TYPE event_type AS ENUM ('search', 'watch');
CREATE TYPE batch_status AS ENUM ('created', 'processing', 'completed', 'failed');
CREATE TYPE delivery_status AS ENUM ('generated', 'prepared', 'sent', 'failed');
CREATE TYPE interest_source AS ENUM ('behavior', 'onboarding', 'manual');
CREATE TYPE window_type AS ENUM ('before_cutoff', 'after_cutoff');
-- 2. users 테이블
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    google_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    interest_categories TEXT DEFAULT '[]',
    -- JSON 배열 문자열
    send_time TEXT NOT NULL DEFAULT '["21:00"]',
    -- JSON 배열 (Issue 7에서 단일 시간 정리 예정)
    is_subscribed BOOLEAN DEFAULT true,
    unsubscribed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivery_type VARCHAR(50) DEFAULT 'email',
    initial_intent VARCHAR(100),
    subscribed_channels TEXT,
    -- DEPRECATED: 행동기록 파이프라인 제거(Issue 8)로 불필요
    oauth_credentials TEXT
);
-- 3. report_batches 테이블 — DEPRECATED: 행동기록 파이프라인 제거(Issue 8)로 불필요
--    기존 DB 호환 유지를 위해 테이블 정의는 유지
CREATE TABLE report_batches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    period_start TIMESTAMP,
    period_end TIMESTAMP,
    status batch_status DEFAULT 'created',
    window_type window_type,
    topic_count INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);
-- 4. behavior_logs 테이블 — DEPRECATED: 행동기록 파이프라인 제거(Issue 8)로 불필요
--    기존 DB 호환 유지를 위해 테이블 정의는 유지
CREATE TABLE behavior_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    event_type event_type NOT NULL,
    keyword TEXT NOT NULL,
    video_id VARCHAR(50),
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status log_status DEFAULT 'pending',
    processed_at TIMESTAMP,
    batch_id UUID REFERENCES report_batches(id) ON DELETE
    SET NULL
);
-- 5. user_interests 테이블 — 하트 토픽 저장 중심으로 개선
--    unique 기준: (user_id, normalized_topic)
CREATE TABLE user_interests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    category TEXT NOT NULL,
    -- 사용자에게 보여줄 대표 토픽명
    normalized_topic VARCHAR(100),
    -- 중복 판단 및 5개 제한 기준 (소문자 정규화)
    weight INTEGER DEFAULT 1,
    -- 하위 호환 유지 (누적 로직은 Issue 8에서 제거)
    source interest_source DEFAULT 'manual',
    -- 하트 기반은 'manual'
    is_active BOOLEAN DEFAULT true,
    -- soft delete (관심 토픽 취소 시 false)
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_interest_normalized UNIQUE (user_id, normalized_topic),
    CONSTRAINT uq_user_interest_category UNIQUE (user_id, category)
);
-- 6. user_interest_videos 테이블 — 관심 토픽에 연결된 하트 영상 (Issue 4)
--    동일 관심 토픽 안에서 같은 video_id 중복 저장 방지
CREATE TABLE user_interest_videos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_interest_id UUID NOT NULL REFERENCES user_interests(id) ON DELETE CASCADE,
    video_id VARCHAR(50) NOT NULL,
    title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_interest_video UNIQUE (user_interest_id, video_id)
);
-- 7. newsletters 테이블
CREATE TABLE newsletters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    batch_id UUID REFERENCES report_batches(id) ON DELETE CASCADE,
    subject TEXT,
    content_json TEXT,
    delivery_status delivery_status DEFAULT 'generated',
    error_message TEXT,
    delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    scheduled_send_time TIMESTAMP,
    -- 사전 생성 시 발송 예정 시각 (UTC) — delivery_status='prepared'일 때 사용
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- 8. 인덱스
CREATE INDEX idx_behavior_logs_status ON behavior_logs (user_id, status, logged_at);
CREATE INDEX idx_behavior_logs_batch_id ON behavior_logs (batch_id);
CREATE INDEX idx_user_interests_user ON user_interests (user_id, weight DESC);
CREATE INDEX idx_user_interests_active ON user_interests (user_id, is_active);
CREATE INDEX idx_newsletters_history ON newsletters (user_id, delivered_at DESC);
CREATE INDEX idx_newsletters_delivery ON newsletters (user_id, delivery_status);
CREATE INDEX idx_report_batches_user ON report_batches (user_id, started_at);
-- ── 기존 DB 마이그레이션 (이미 운영 중인 DB에 적용) ──────────────────────────
-- 아래 구문은 기존 DB에 순서대로 실행하세요. 신규 설치 시에는 불필요합니다.
-- user_interests: normalized_topic 컬럼 추가
-- ALTER TABLE user_interests ADD COLUMN IF NOT EXISTS normalized_topic VARCHAR(100);
-- user_interests: is_active 컬럼 추가
-- ALTER TABLE user_interests ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true;
-- user_interests: source default를 'manual'로 변경
-- ALTER TABLE user_interests ALTER COLUMN source SET DEFAULT 'manual';
-- user_interests: normalized_topic 기준 unique 제약 추가
-- UPDATE user_interests SET normalized_topic = lower(trim(category)) WHERE normalized_topic IS NULL;
-- ALTER TABLE user_interests ADD CONSTRAINT uq_user_interest_normalized UNIQUE (user_id, normalized_topic);
-- user_interest_videos 신규 테이블 생성 (Issue 4)
-- CREATE TABLE IF NOT EXISTS user_interest_videos (
--     id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
--     user_interest_id UUID NOT NULL REFERENCES user_interests(id) ON DELETE CASCADE,
--     video_id         VARCHAR(50) NOT NULL,
--     title            TEXT,
--     created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
--     CONSTRAINT uq_interest_video UNIQUE (user_interest_id, video_id)
-- );
-- ── 뉴스레터 정시 발송 (사전 생성) 마이그레이션 ──────────────────────────────
-- delivery_status enum에 'prepared' 추가
-- 주의: PostgreSQL ENUM 값 추가는 트랜잭션 밖에서 실행해야 합니다
-- ALTER TYPE delivery_status ADD VALUE IF NOT EXISTS 'prepared';
-- newsletters: 사전 생성 발송 예정 시각 컬럼 추가
-- ALTER TABLE newsletters ADD COLUMN IF NOT EXISTS scheduled_send_time TIMESTAMP;
-- 사전 생성 뉴스레터 조회용 인덱스
-- CREATE INDEX IF NOT EXISTS idx_newsletters_prepared
--     ON newsletters (user_id, delivery_status, scheduled_send_time)
--     WHERE delivery_status = 'prepared';
