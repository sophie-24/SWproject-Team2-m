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
    google_id VARCHAR(255) UNIQUE NOT NULL, -- Google OAuth 식별용
    email VARCHAR(255) UNIQUE NOT NULL,
    interest_categories JSONB DEFAULT '[]'::jsonb,
    send_time JSONB NOT NULL DEFAULT '["08:00", "20:00"]'::jsonb,
    is_subscribed BOOLEAN DEFAULT true,
    unsubscribed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    delivery_type VARCHAR(50) DEFAULT 'email',
    initial_intent VARCHAR(100)
);

-- 3. report_batches 테이블 (발송 시간 기준 뉴스레터 묶음)
CREATE TABLE report_batches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    status batch_status DEFAULT 'created',
    window_type window_type NOT NULL,
    topic_count INTEGER DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE
);

-- 4. behavior_logs 테이블 (오늘의 검색/시청 로그)
CREATE TABLE behavior_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type event_type NOT NULL,
    keyword TEXT NOT NULL,
    video_id VARCHAR(50), -- watch일 때 사용
    logged_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status log_status DEFAULT 'pending',
    processed_at TIMESTAMP WITH TIME ZONE,
    batch_id UUID REFERENCES report_batches(id) ON DELETE SET NULL
);

-- 5. user_interests 테이블 (장기 관심사, 개인화 기억)
CREATE TABLE user_interests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    weight INTEGER DEFAULT 1,
    source interest_source DEFAULT 'behavior',
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_user_interest_category UNIQUE(user_id, category)
);

-- 6. newsletters 테이블 (최종 뉴스레터 결과 및 발송 상태)
CREATE TABLE newsletters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    batch_id UUID UNIQUE REFERENCES report_batches(id) ON DELETE CASCADE,
    subject TEXT,
    content_json JSONB,
    delivery_status delivery_status DEFAULT 'generated',
    error_message TEXT,
    delivered_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. 인덱스 추가 (조회 성능 최적화)
CREATE INDEX idx_behavior_logs_pending
ON behavior_logs (user_id, status)
WHERE status = 'pending';

CREATE INDEX idx_user_interests_ranking
ON user_interests (user_id, weight DESC);
