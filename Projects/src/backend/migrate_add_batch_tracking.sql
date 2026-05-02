-- ============================================================
-- Migration: Batch Tracking + User Interests
-- 실행: pgAdmin 쿼리 창에서 직접 실행
-- 멱등성 보장: IF NOT EXISTS / ON CONFLICT DO NOTHING
-- ============================================================

-- 1) behavior_logs: status + batch_id 추가
ALTER TABLE behavior_logs
    ADD COLUMN IF NOT EXISTS status   VARCHAR(20)  NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS batch_id UUID         NULL;

-- 기존 로그는 이미 배치에서 처리 불가 → archived 처리 (선택적)
-- UPDATE behavior_logs SET status = 'archived' WHERE status = 'pending';

-- 2) newsletters: delivery_status + error_message + batch_id 추가
ALTER TABLE newsletters
    ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(20) NOT NULL DEFAULT 'sent',
    ADD COLUMN IF NOT EXISTS error_message   TEXT        NULL,
    ADD COLUMN IF NOT EXISTS batch_id        UUID        NULL;

-- 기존 뉴스레터는 발송 완료로 간주 (이미 DEFAULT 'sent' 적용됨)

-- 3) report_batches 테이블 신규 생성
CREATE TABLE IF NOT EXISTS report_batches (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     VARCHAR(255) NOT NULL,
    started_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP    NULL,
    status      VARCHAR(20)  NOT NULL DEFAULT 'running',
    log_count   INTEGER      NULL,
    topic_count INTEGER      NULL
);

-- 4) user_interests 테이블 신규 생성
CREATE TABLE IF NOT EXISTS user_interests (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    VARCHAR(255) NOT NULL,
    category   VARCHAR(100) NOT NULL,
    weight     INTEGER      NOT NULL DEFAULT 1,
    updated_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_interest_category UNIQUE (user_id, category)
);

-- 온보딩 완료 유저의 interest_categories → user_interests 마이그레이션 (선택적)
-- interest_categories 컬럼은 JSON 배열 문자열이므로 jsonb_array_elements_text 사용
INSERT INTO user_interests (user_id, category, weight, updated_at)
SELECT
    google_id,
    trim(cat::text, '"') AS category,
    1                    AS weight,
    NOW()                AS updated_at
FROM users,
     jsonb_array_elements(interest_categories::jsonb) AS cat
WHERE interest_categories IS NOT NULL
  AND interest_categories != '[]'
ON CONFLICT (user_id, category) DO NOTHING;

-- 5) users 테이블 신규 컬럼 추가 (기존 서버에서 누락된 경우)
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_subscribed      BOOLEAN     NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS unsubscribed_at    TIMESTAMP   NULL,
    ADD COLUMN IF NOT EXISTS morning_send_time  VARCHAR(5)  NOT NULL DEFAULT '08:00',
    ADD COLUMN IF NOT EXISTS initial_intent     VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS interest_categories TEXT       NULL;

-- 6) user_subscriptions 테이블 신규 생성 (YouTube 구독 채널 영구 저장)
CREATE TABLE IF NOT EXISTS user_subscriptions (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       VARCHAR(255) NOT NULL,
    channel_id    VARCHAR(100) NOT NULL,
    channel_title VARCHAR(255) NULL,
    synced_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_subscription UNIQUE (user_id, channel_id)
);

-- 7) 인덱스
CREATE INDEX IF NOT EXISTS idx_behavior_logs_status    ON behavior_logs      (user_id, status, logged_at);
CREATE INDEX IF NOT EXISTS idx_behavior_logs_batch_id  ON behavior_logs      (batch_id);
CREATE INDEX IF NOT EXISTS idx_newsletters_history     ON newsletters         (user_id, delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_newsletters_delivery    ON newsletters         (user_id, delivery_status);
CREATE INDEX IF NOT EXISTS idx_report_batches_user     ON report_batches      (user_id, started_at);
CREATE INDEX IF NOT EXISTS idx_user_interests_user     ON user_interests      (user_id, weight DESC);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user ON user_subscriptions  (user_id);
