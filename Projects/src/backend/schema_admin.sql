-- ── Admin 전용 신규 테이블 (마이그레이션용) ──────────────────────────────────

-- ── 기존 테이블 칼럼 마이그레이션 ────────────────────────────────────────────

-- user_interests: is_active, normalized_topic, source, weight 칼럼 추가
ALTER TABLE user_interests ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_interests ADD COLUMN IF NOT EXISTS normalized_topic VARCHAR(100);
ALTER TABLE user_interests ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'manual';
ALTER TABLE user_interests ADD COLUMN IF NOT EXISTS weight INTEGER NOT NULL DEFAULT 1;
ALTER TABLE user_interests ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP;
ALTER TABLE user_interests ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_user_interests_active ON user_interests (user_id, is_active);

-- newsletters: scheduled_send_time, batch_id, error_message 칼럼 추가
ALTER TABLE newsletters ADD COLUMN IF NOT EXISTS scheduled_send_time TIMESTAMP;
ALTER TABLE newsletters ADD COLUMN IF NOT EXISTS batch_id UUID;
ALTER TABLE newsletters ADD COLUMN IF NOT EXISTS error_message TEXT;

-- users: 신규 칼럼 추가
ALTER TABLE users ADD COLUMN IF NOT EXISTS initial_intent VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS interest_categories TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_subscribed BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS unsubscribed_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscribed_channels TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS watched_channels TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_credentials TEXT;


-- 0. analysis_runs — 파이프라인 실행 로그 (대시보드 관측용)
CREATE TABLE IF NOT EXISTS analysis_runs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_type      VARCHAR(20)  DEFAULT 'watch',      -- watch | search | admin_test | newsletter
    video_id          VARCHAR(50),
    keyword           TEXT,
    user_id           VARCHAR(255),
    status            VARCHAR(20)  DEFAULT 'completed',  -- completed | failed
    started_at        TIMESTAMP    DEFAULT NOW(),
    finished_at       TIMESTAMP,
    total_latency_ms  INTEGER,
    cache_hit         BOOLEAN      DEFAULT false,
    transcript_source VARCHAR(20),                       -- youtube-transcript-api | yt-dlp | supadata | none
    transcript_len    INTEGER,
    ad_score          INTEGER,
    credibility_score INTEGER,
    error_message     TEXT
);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_started ON analysis_runs (started_at);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_type ON analysis_runs (request_type, started_at);

-- 1. admin_accounts — Admin 계정 관리
CREATE TABLE IF NOT EXISTS admin_accounts (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50)  UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,  -- bcrypt (현재는 ADMIN_SECRET 직접 비교)
    email         VARCHAR(100),
    role          VARCHAR(20)  DEFAULT 'admin',
    is_active     BOOLEAN      DEFAULT true,
    created_at    TIMESTAMP    DEFAULT NOW(),
    updated_at    TIMESTAMP    DEFAULT NOW(),
    last_login    TIMESTAMP
);

-- 2. demo_gallery_samples — Demo Gallery 샘플 데이터
CREATE TABLE IF NOT EXISTS demo_gallery_samples (
    id            SERIAL PRIMARY KEY,
    video_id      VARCHAR(100) NOT NULL,
    title         TEXT         NOT NULL,
    channel       VARCHAR(100),
    intent        VARCHAR(50),             -- Learning / News / Review / Other
    trust_score   INTEGER      DEFAULT 0,  -- 0~100
    ad_detected   VARCHAR(10)  DEFAULT 'No', -- No / Yes / Partial
    summary       TEXT,
    keywords      TEXT,                    -- JSON 배열 문자열
    thumbnail_url TEXT,
    views         VARCHAR(20),
    display_order INTEGER      DEFAULT 0,
    is_featured   BOOLEAN      DEFAULT false,
    created_at    TIMESTAMP    DEFAULT NOW()
);

-- 3. admin_logs — Admin 작업 감사 로그
CREATE TABLE IF NOT EXISTS admin_logs (
    id         SERIAL PRIMARY KEY,
    username   VARCHAR(50),
    action     VARCHAR(100),  -- login, logout, delete_user, test_analysis, etc.
    details    TEXT,          -- JSON 문자열
    created_at TIMESTAMP DEFAULT NOW()
);

-- ── Demo Gallery 샘플 초기 데이터 ────────────────────────────────────────────
INSERT INTO demo_gallery_samples
    (video_id, title, channel, intent, trust_score, ad_detected, summary, keywords, thumbnail_url, views, display_order, is_featured)
VALUES
    ('dQw4w9WgXcQ', 'AI 기술 입문 강의', 'Tech School', 'Learning', 89, 'No',
     'AI의 기본 개념을 쉽게 설명하는 고품질 교육 콘텐츠입니다. 머신러닝, 딥러닝의 핵심 원리를 실생활 사례와 함께 소개합니다.',
     '["AI", "머신러닝", "딥러닝", "교육"]',
     'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg', '123K', 1, true),

    ('abc123xyz01', '마케팅 전략 분석 2026', 'Marketing Pro', 'News', 76, 'Partial',
     '최신 디지털 마케팅 트렌드와 데이터 기반 전략을 분석합니다. SNS 광고 효율화 방법론을 중심으로 설명합니다.',
     '["마케팅", "디지털", "SNS", "전략"]',
     'https://img.youtube.com/vi/abc123xyz01/mqdefault.jpg', '87K', 2, false),

    ('py_tutorial_01', 'Python 완전정복 튜토리얼', 'Code Master', 'Learning', 92, 'No',
     '파이썬 초급부터 중급까지 체계적으로 배울 수 있는 완성도 높은 튜토리얼입니다. 실습 중심의 커리큘럼으로 구성되었습니다.',
     '["Python", "프로그래밍", "코딩", "튜토리얼"]',
     'https://img.youtube.com/vi/py_tutorial_01/mqdefault.jpg', '456K', 3, true),

    ('tech_news_2026', '최신 기술 뉴스 브리핑', 'Tech News Daily', 'News', 72, 'No',
     '이번 주 주요 기술 뉴스를 빠르게 정리합니다. AI 칩 경쟁, 오픈소스 LLM 현황 등을 다룹니다.',
     '["테크뉴스", "AI칩", "LLM", "뉴스"]',
     'https://img.youtube.com/vi/tech_news_2026/mqdefault.jpg', '34K', 4, false),

    ('product_review_01', '갤럭시 S26 울트라 완벽 리뷰', 'Product Reviews', 'Review', 68, 'Yes',
     '갤럭시 S26 울트라의 카메라, 성능, 배터리를 심층 리뷰합니다. 전작 대비 개선 사항을 상세히 비교합니다.',
     '["갤럭시", "리뷰", "스마트폰", "카메라"]',
     'https://img.youtube.com/vi/product_review_01/mqdefault.jpg', '201K', 5, false),

    ('web_dev_adv', '웹 개발 심화: React 19 완전 가이드', 'Dev Academy', 'Learning', 88, 'No',
     'React 19의 새로운 기능을 실전 프로젝트와 함께 학습합니다. Server Components와 Actions를 중심으로 설명합니다.',
     '["React", "웹개발", "프론트엔드", "JavaScript"]',
     'https://img.youtube.com/vi/web_dev_adv/mqdefault.jpg', '78K', 6, true),

    ('finance_daily', '경제 뉴스 분석 — 금리 전망', 'Finance Daily', 'News', 81, 'No',
     '2026년 하반기 금리 전망과 주요국 통화정책 변화를 분석합니다. 투자자라면 알아야 할 핵심 내용만 정리했습니다.',
     '["경제", "금리", "투자", "통화정책"]',
     'https://img.youtube.com/vi/finance_daily/mqdefault.jpg', '52K', 7, false),

    ('startup_story', '스타트업 창업 이야기 — 0에서 100억까지', 'Startup Stories', 'Other', 75, 'No',
     '국내 스타트업 창업자의 생생한 경험담입니다. 아이디어 검증부터 시리즈 A 투자 유치까지 실전 노하우를 공유합니다.',
     '["스타트업", "창업", "투자", "성장"]',
     'https://img.youtube.com/vi/startup_story/mqdefault.jpg', '95K', 8, false)
ON CONFLICT DO NOTHING;
