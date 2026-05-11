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
    ADD COLUMN IF NOT EXISTS initial_intent     VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS interest_categories TEXT       NULL;

-- 6) user_subscriptions — 구독 채널 DB 저장 방식 폐기, YouTube API 실시간 조회로 대체

-- ============================================================
-- Migration v2: 2차 DB 설계 반영
-- ============================================================

-- v2-1) behavior_logs: processed_at 추가
ALTER TABLE behavior_logs
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMP NULL;

-- v2-2) user_interests: source / last_seen_at / created_at 추가
ALTER TABLE user_interests
    ADD COLUMN IF NOT EXISTS source       VARCHAR(20) NOT NULL DEFAULT 'behavior',
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP   NULL,
    ADD COLUMN IF NOT EXISTS created_at   TIMESTAMP   NOT NULL DEFAULT NOW();

-- 온보딩에서 생성된 기존 관심사 source → 'onboarding' 으로 소급 적용 (선택적)
-- UPDATE user_interests SET source = 'onboarding' WHERE created_at = updated_at;

-- v2-3) report_batches: window_type / period_start / period_end 추가
ALTER TABLE report_batches
    ADD COLUMN IF NOT EXISTS window_type  VARCHAR(30) NULL,
    ADD COLUMN IF NOT EXISTS period_start TIMESTAMP   NULL,
    ADD COLUMN IF NOT EXISTS period_end   TIMESTAMP   NULL;

-- ============================================================
-- Migration v3: send_time JSON 배열 통합
-- ============================================================

-- v3-1) send_time 컬럼 타입 먼저 TEXT로 변경 (VARCHAR(5) → TEXT)
ALTER TABLE users
    ALTER COLUMN send_time TYPE TEXT,
    ALTER COLUMN send_time SET DEFAULT '["21:00"]';

-- v3-2) 기존 send_time 값을 JSON 배열 형태로 변환 ("21:00" → '["21:00"]')
UPDATE users
SET send_time = '["' || send_time || '"]'
WHERE send_time IS NOT NULL
  AND send_time NOT LIKE '[%';

-- v3-3) newsletters.delivery_type 컬럼 제거
ALTER TABLE newsletters
    DROP COLUMN IF EXISTS delivery_type;

-- ============================================================
-- Migration v4: 구독 채널 ID 캐시 컬럼 추가
-- ============================================================

-- v4-1) users.subscribed_channels — 유튜브 구독 채널 ID JSON 배열 캐시
--        GET /subscriptions 호출 시 갱신, scheduler selector_ai 가산점에 활용
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS subscribed_channels TEXT NULL;

-- ============================================================
-- Migration v5: OAuth credentials DB 저장
-- ============================================================

-- v5-1) users.oauth_credentials — Google OAuth credentials JSON 저장
--        로그인 시 저장, 서버 재시작 후 /subscriptions 호출에 활용
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS oauth_credentials TEXT NULL;

-- 7) 인덱스
CREATE INDEX IF NOT EXISTS idx_behavior_logs_status    ON behavior_logs      (user_id, status, logged_at);
CREATE INDEX IF NOT EXISTS idx_behavior_logs_batch_id  ON behavior_logs      (batch_id);
CREATE INDEX IF NOT EXISTS idx_newsletters_history     ON newsletters         (user_id, delivered_at DESC);
CREATE INDEX IF NOT EXISTS idx_newsletters_delivery    ON newsletters         (user_id, delivery_status);
CREATE INDEX IF NOT EXISTS idx_report_batches_user     ON report_batches      (user_id, started_at);
CREATE INDEX IF NOT EXISTS idx_user_interests_user     ON user_interests      (user_id, weight DESC);
