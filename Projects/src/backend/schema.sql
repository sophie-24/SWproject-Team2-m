-- 1. 확장 및 ENUM 타입 정의
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TYPE log_status AS ENUM ('pending', 'processed', 'archived');
CREATE TYPE event_type AS ENUM ('search', 'watch');
CREATE TYPE batch_status AS ENUM ('created', 'processing', 'completed', 'failed');
CREATE TYPE delivery_status AS ENUM ('generated', 'sent', 'failed');
CREATE TYPE interest_source AS ENUM ('behavior', 'onboarding', 'manual');
CREATE TYPE window_type AS ENUM ('before_cutoff', 'after_cutoff');
-- 2. users 테이블 (사용자 정보, 온보딩 관심사, 발송시간)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    google_id VARCHAR(255) UNIQUE NOT NULL,
    -- Google OAuth 식별용 (백엔드 user_id 기준)
    email VARCHAR(255) UNIQUE NOT NULL,
    interest_categories TEXT DEFAULT '[]',
    -- JSON 배열 문자열
    send_time TEXT NOT NULL DEFAULT '["21:00"]',
    -- JSON 배열 문자열 (예: '["08:00","21:00"]')
    is_subscribed BOOLEAN DEFAULT true,
    unsubscribed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivery_type VARCHAR(50) DEFAULT 'email',
    initial_intent VARCHAR(100),
    subscribed_channels TEXT,
    -- YouTube 구독 채널 ID JSON 배열 캐시
    oauth_credentials TEXT -- Google OAuth credentials JSON
);
-- 3. report_batches 테이블 (발송 시간 기준 뉴스레터 묶음)
CREATE TABLE report_batches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    -- google_id 기준
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,
    status batch_status DEFAULT 'created',
    window_type window_type NOT NULL,
    topic_count INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);
-- 4. behavior_logs 테이블 (오늘의 검색/시청 로그)
CREATE TABLE behavior_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    -- google_id 기준
    event_type event_type NOT NULL,
    keyword TEXT NOT NULL,
    video_id VARCHAR(50),
    -- watch일 때 사용
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status log_status DEFAULT 'pending',
    processed_at TIMESTAMP,
    batch_id UUID REFERENCES report_batches(id) ON DELETE
    SET NULL
);
-- 5. user_interests 테이블 (장기 관심사, 개인화 기억)
CREATE TABLE user_interests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    -- google_id 기준
    category TEXT NOT NULL,
    weight INTEGER DEFAULT 1,
    source interest_source DEFAULT 'behavior',
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_interest_category UNIQUE(user_id, category)
);
-- 6. newsletters 테이블 (최종 뉴스레터 결과 및 발송 상태)
CREATE TABLE newsletters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    -- google_id 기준
    batch_id UUID UNIQUE REFERENCES report_batches(id) ON DELETE CASCADE,
    subject TEXT,
    content_json TEXT,
    -- JSON 문자열
    delivery_status delivery_status DEFAULT 'generated',
    error_message TEXT,
    delivered_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- 7. 인덱스 추가 (조회 성능 최적화)
CREATE INDEX idx_behavior_logs_pending ON behavior_logs (user_id, status)
WHERE status = 'pending';
CREATE INDEX idx_behavior_logs_status ON behavior_logs (user_id, status, logged_at);
CREATE INDEX idx_behavior_logs_batch_id ON behavior_logs (batch_id);
CREATE INDEX idx_user_interests_ranking ON user_interests (user_id, weight DESC);
CREATE INDEX idx_newsletters_history ON newsletters (user_id, delivered_at DESC);
CREATE INDEX idx_newsletters_delivery ON newsletters (user_id, delivery_status);
CREATE INDEX idx_report_batches_user ON report_batches (user_id, started_at);
