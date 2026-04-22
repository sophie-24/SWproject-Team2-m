# Tubify — 서비스 설계 전체 분석서
> 기획자 시점의 화면 설계서 + 구조 분석 + 보완 항목 정리  
> 작성일: 2026-04-19

---

## 1. 서비스 전체 조감도

```
┌──────────────────────────────────────────────────────────────────────┐
│                         TUBIFY 서비스                                │
│                                                                      │
│  ┌─────────────────────┐    ┌──────────────────────────────────────┐ │
│  │  PIPELINE A         │    │  PIPELINE B                          │ │
│  │  라이브 서치 (실시간)│    │  뉴스레터 (배치)                     │ │
│  │                     │    │                                      │ │
│  │  유튜브 검색         │    │  유튜브 시청 행동 수집               │ │
│  │  → Side Panel       │    │  → 08:00/21:00 배치                  │ │
│  │  → /analyze_search  │    │  → 이메일 발송                       │ │
│  │  → 즉시 AI 분석     │    │  → 오늘 로그 + 프로필 합산           │ │
│  └─────────────────────┘    └──────────────────────────────────────┘ │
│                                                                      │
│  공유 레이어: selector_ai + analyzer_ai                              │
│  독립 레이어: cluster_ai / intent_ai / newsletter_ai (B 전용)        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. 화면 설계서 (Screen Design Document)

### 2-1. 랜딩 페이지 (`index.html`)

**역할**: 서비스 첫 진입, 로그인 유도  
**현재 상태**: 구현됨 (정적 소개 페이지)

```
┌─────────────────────────────────────────────┐
│  ✦ Tubify                          [Google 로그인] │
├─────────────────────────────────────────────┤
│                                             │
│  유튜브 알고리즘 대신,                       │
│  오늘 당신이 궁금했던 것만.                   │
│                                             │
│  [Google로 시작하기 →]                       │
│                                             │
│  Feature 카드 3개 (라이브서치 / 뉴스레터 / AI) │
└─────────────────────────────────────────────┘
```

**필요한 상태 분기**:
- 미로그인: Google 로그인 버튼
- 로그인됨: 대시보드 바로 이동 or "이미 로그인됨" 표시

**현재 누락**: 로그인 상태 감지 후 자동 리다이렉트 로직 없음

---

### 2-2. 온보딩 (`onboarding.html`) — 3-Step

**역할**: 신규 유저의 프로필 초기화  
**현재 상태**: 구현됨 (3단계 플로우)

```
Step 1: 이메일 + 수신 시간 설정
┌─────────────────────────────────────────────┐
│  ① 이메일 등록                              │
│  ┌─────────────────────────────┐            │
│  │ example@email.com           │            │
│  └─────────────────────────────┘            │
│  발송 시간: [오전 8시] [오후 9시]            │
│  [다음 →]                                   │
└─────────────────────────────────────────────┘

Step 2: 관심사 프로필 생성
┌─────────────────────────────────────────────┐
│  ② 관심사 분석 중...                        │
│  ┌────────────────────────────────────────┐  │
│  │ 분석된 태그: [파이썬] [머신러닝] [React] │  │
│  └────────────────────────────────────────┘  │
│  + 직접 추가: [        ] [추가]              │
│  성향: [지식형 🧠] [유희형 😄] [구매형 🛒]   │
│  [다음 →]                                   │
└─────────────────────────────────────────────┘

Step 3: 익스텐션 설치 안내
┌─────────────────────────────────────────────┐
│  ③ 크롬 익스텐션 설치                       │
│  [Chrome 웹스토어에서 설치 →]               │
│  설치 후 자동 연동됩니다 ✓                  │
└─────────────────────────────────────────────┘
```

**API 흐름**:
```
Step 1: POST /subscribe { email, delivery_type, send_time }
Step 2: POST /profile/analyze-history { keywords: [...] }
        ← chrome.history API → 검색어 추출
Step 3: POST /profile/init { initial_intent, interest_categories }
```

**현재 누락/보완점**:
- chrome.history 기간이 90일 (PPT는 1년) — maxResults 조정 필요
- 이메일 중복 체크 없음
- Step 3에서 익스텐션 이미 설치됐는지 감지 로직 없음
- 온보딩 완료 후 → 대시보드 자동 이동 없음

---

### 2-3. 크롬 익스텐션 팝업 (`popup.html`)

**역할**: 유튜브에서 빠른 검색 요약 + Pipeline A 진입점  
**현재 상태**: 구현됨

```
[미로그인 상태]
┌─────────────────┐
│ ✦ Tubify        │
│                 │
│ 서버: 🟢 정상   │
│                 │
│ [Google 로그인] │
└─────────────────┘

[로그인 + 유튜브 검색 중]
┌─────────────────────────────────┐
│ ✦ Tubify          규리@gmail   │
├─────────────────────────────────┤
│ 🔍 "파이썬 입문"               │
│ ─────────────────────────────  │
│ 📺 파이썬 입문 강좌 2024       │
│ 📺 파이썬 기초 - 1시간 완성    │
│ 📺 ...                         │
│ ─────────────────────────────  │
│ [AI 분석 대시보드 열기 →]      │
│ ─────────────────────────────  │
│ [로그아웃]                     │
└─────────────────────────────────┘

[유튜브가 아닌 페이지]
┌─────────────────────────────────┐
│ ✦ Tubify                        │
│ 유튜브 페이지에서 사용하세요    │
└─────────────────────────────────┘
```

**현재 누락/보완점**:
- 로그인 후 polling 방식(2초 간격 30초) → 웹훅/메시지 방식이 더 적합
- 유튜브 검색 페이지가 아닌 /watch 페이지일 때 상태 없음
- 오늘 수집된 로그 수 / 트리거된 주제 미표시

---

### 2-4. Chrome Side Panel (`side_panel.html`) — Pipeline A 핵심

**역할**: /analyze_search 결과 렌더링 (유튜브 옆에 표시)  
**현재 상태**: 구현됨

```
[로딩 중]
┌─────────────────────────────────────┐
│ ✦ Tubify    🔍 "파이썬 입문"        │
├─────────────────────────────────────┤
│                                     │
│  [✓] 유튜브에서 영상 수집 중        │
│  [⟳] AI 자막 분석 중...            │
│  [ ] AI 교차 분석                   │
│                                     │
└─────────────────────────────────────┘

[결과 렌더링]
┌─────────────────────────────────────┐
│ ✦ Tubify    🔍 "파이썬 입문"        │
├─────────────────────────────────────┤
│ 📌 공통 사실                        │
│  · 파이썬은 인터프리터 언어         │
│  · 들여쓰기로 블록 구분             │
│                                     │
│ ⚡ 주요 쟁점                        │
│  · 파이썬 3 vs 2 생태계 단절       │
│                                     │
│ ─── 추천 영상 ──────────────────── │
│                                     │
│ [썸네일] 파이썬 입문 강좌 2024     │
│          채널명 · 🔴 광고없음       │
│          신뢰도 ████░ 82%          │
│          "초보자를 위한 파이썬..."  │
│                                     │
│ [썸네일] 파이썬 기초 1시간 완성    │
│          ...                        │
└─────────────────────────────────────┘
```

**현재 누락/보완점**:
- 유튜브 탭 변경 시 (다른 검색어로 이동) Side Panel 자동 갱신 로직 없음
- 분석 결과를 "저장하기" / "뉴스레터에 추가" 기능 없음
- 영상 클릭 → 현재 탭에서 유튜브 이동 시 Side Panel 유지 여부 확인 필요
- 캐시 hit 시 로딩 없이 즉시 표시 (UX 개선 필요 — 캐시임을 안내해야 함)

---

### 2-5. 대시보드 (`dashboard.html`)

**역할**: Pipeline B 뉴스레터 히스토리 + 사용자 설정  
**현재 상태**: 부분 구현 (히스토리 조회만)

```
현재 구현된 모습:
┌─────────────────────────────────────────────┐
│ ✦ Tubify                     [로그아웃]     │
├─────────────────────────────────────────────┤
│ 📬 내 뉴스레터 히스토리                     │
│                                             │
│ ┌─── 2024-04-19 저녁 뉴스레터 ──────────┐  │
│ │ 🧠 지식형 · "파이썬 생태계 동향"       │  │
│ │ ├ 토픽 1: 파이썬 3.12 새기능           │  │
│ │ │  요약 · 장단점 · 출처 링크           │  │
│ │ └ 토픽 2: AI 프레임워크 비교           │  │
│ └────────────────────────────────────────┘  │
│                                             │
│ (빈 상태: "📭 아직 발송된 뉴스레터 없음")  │
└─────────────────────────────────────────────┘

필요하지만 없는 모습:
┌─────────────────────────────────────────────┐
│ ✦ Tubify                     [로그아웃]     │
├──────────────┬──────────────────────────────┤
│ 📋 내 활동   │  📬 뉴스레터 히스토리        │
│              │                              │
│ 오늘 검색:  │  [2024-04-19 저녁]           │
│ · 파이썬 ×3 │  [2024-04-18 아침]           │
│ · React ×2  │  [2024-04-17 저녁]           │
│              │                              │
│ 관심사 태그: │  ─────────────────────────  │
│ [파이썬]     │                              │
│ [머신러닝]   │  ⚙️ 설정                     │
│ [React]      │  발송 시간: [오전8시 ▼]     │
│              │  이메일: user@gmail.com      │
│ 합산 키워드: │  관심사: [편집]              │
│ 10개 → 발송  │  [저장]                     │
└──────────────┴──────────────────────────────┘
```

**현재 누락 기능**:
1. 오늘 행동 로그 / 트리거된 주제 표시 (`GET /my/logs` 결과 활용)
2. 관심사 프로필 편집 UI
3. 발송 시간 변경 (`PUT /settings/send_time`)
4. 이메일 변경
5. 구독 해지 / 일시 정지
6. 뉴스레터 개별 항목 클릭 → 상세 보기 (content_json 전체)

---

### 2-6. 관리자 대시보드 (`admin.html`)

**역할**: 개발/테스트용 내부 관리 페이지  
**현재 상태**: 부분 구현

```
┌─────────────────────────────────────────────┐
│ 🔑 관리자 대시보드          [ADMIN_SECRET]  │
├──────────────┬──────────────────────────────┤
│ 👤 유저 목록 │ 📋 오늘 행동 로그             │
│              │                              │
│ 이메일       │ user_id | 이벤트 | 키워드    │
│ 수신방법     │ abc123  | search | 파이썬    │
│ 가입일       │ abc123  | watch  | 파이썬...  │
│              │                              │
├──────────────┤──────────────────────────────┤
│ ⚡ 즉시 실행 │                              │
│ user_id: [  ]│                              │
│ [파이프라인  │                              │
│  즉시 실행]  │                              │
└──────────────┴──────────────────────────────┘
```

**현재 누락**:
- 배치 스케줄러 수동 전체 실행 버튼
- 뉴스레터 발송 이력 패널
- 유저별 오늘 트리거 주제 미리보기

---

## 3. 데이터 플로우 전체 구조

### 3-1. Pipeline A (라이브 서치) 데이터 흐름

```
[사용자] 유튜브에서 "파이썬 강의" 검색
    │
    ▼
[content.js]
  · URL 파싱: search_query = "파이썬 강의"
  · /collect POST → DB: behavior_logs (event_type="search")
  · 플로팅 버튼 활성화
    │
    ▼ (버튼 클릭 or 팝업 클릭)
[background.js]
  · chrome.sidePanel.open({ tabId })
    │
    ▼
[side_panel.html] 오픈
  · chrome.storage.local → JWT 읽기
  · chrome.tabs.query → URL → keyword="파이썬 강의"
    │
    ▼
[GET /analyze_search?keyword=파이썬 강의]  (JWT)
    │
    ├─ 캐시 HIT → 즉시 반환 (_search_analysis_cache)
    │
    └─ 캐시 MISS → asyncio.to_thread(_run)
         │
         ▼
    [selector_ai.select_top_videos("파이썬 강의")]
         · YouTube API 검색 (max 10개)
         · 쇼츠 제거 (60초 이하)
         · ViewRate = 조회수/경과시간(시간)
         · personalization = keyword_sim×0.5 + subscribed×0.2 + recency×0.3
         · pre_score = norm_view_rate × personalization
         · 상위 5개 선정
         │
         ▼
    [analyzer_ai.analyze_videos("파이썬 강의", 5개 영상)]
         · ThreadPoolExecutor(max_workers=5)
         · 각 영상: 자막 추출 → Gemini 분석 (ad_score, summary, credibility)
         · 교차 분석: common_facts, controversies
         · Gemini 총 6회 호출
         │
         ▼
    캐시 저장 → JSONResponse 반환
    │
    ▼
[side_panel.html 렌더링]
  · 영상 카드 (썸네일, 광고배지, 신뢰도%, 요약)
  · 공통 사실 섹션
  · 쟁점 섹션

⚠️ DB 저장 없음 — Pipeline A는 인메모리 캐시만 사용
```

### 3-2. Pipeline B (뉴스레터) 데이터 흐름

```
[PHASE 1: 온보딩] — 1회성
    │
    ▼
POST /subscribe → users.send_time, users.email 저장
    │
    ▼
chrome.history → POST /profile/analyze-history
  · cluster_ai → 관심사 카테고리 추출
  · intent_ai → initial_intent 추론
    │
    ▼
POST /profile/init → users.initial_intent, users.interest_categories 저장

[PHASE 2: 일상 행동 수집]
    │
    ▼
[content.js] 유튜브에서 검색/시청 시 /collect POST
  → behavior_logs DB INSERT
  → 같은 키워드 2회 이상: trigger.py가 탐지 → triggered_topics

[PHASE 3: 배치 실행] — 08:00 or 21:00 KST
    │
    ▼
scheduler._run_batch_for_send_time("21:00")
  · DB: SELECT * FROM users WHERE send_time = '21:00'
  │
  ▼ 각 유저에 대해:
  ├─ get_today_logs(db, user_id) → triggered_topics
  ├─ _get_profile_keywords(user) → profile_keywords
  ├─ _merge_keywords(triggered, profile) → merged_topics (최대 10개)
  │
  ▼
asyncio.to_thread(run_pipeline,
  user_id=...,
  raw_keywords=merged_topics,
  initial_intent=user.initial_intent
)
  │
  ▼
[orchestrator.run_pipeline()]
  Step 0: intent_ai(merged_topics) → intent_type
          format_ai(intent_type) → format_style (Gemini 0회)
  Step 1: cluster_ai(merged_topics, max_topics=5) → clusters (Gemini 1회)
  Step 2-3: 각 cluster에 대해:
            selector_ai(topic, []) → 상위 5개 영상
            analyzer_ai(topic, 5개 영상) → 분석 결과 (Gemini 5+1회)
  Step 4: newsletter_ai(analyses, format_style, intent_type) → 뉴스레터 (Gemini 1회)
  │
  ▼
DB: INSERT INTO newsletters (user_id, subject, content_json, ...)
  │
  ▼
resend.Emails.send(from, to, subject, html)
  → 이메일 수신
```

---

## 4. 멀티 에이전트 호출 구조 분석

### 4-1. 현재 호출 구조 (실제)

```
orchestrator.run_pipeline()
    │
    ├── [병렬 가능하지만 현재 순차]
    │   intent_ai.classify_intent()    → Gemini ×1
    │   format_ai.decide_format()      → 규칙 기반, Gemini 없음
    │
    ├── cluster_ai.cluster_topics()    → Gemini ×1
    │
    ├── [주제 수 × 순차]  ← ⚠️ 병렬화 미구현
    │   ├── selector_ai.select_top_videos("주제1")   → YouTube API
    │   ├── analyzer_ai.analyze_videos("주제1", [...]) → Gemini ×6
    │   ├── selector_ai.select_top_videos("주제2")
    │   └── analyzer_ai.analyze_videos("주제2", [...]) → Gemini ×6
    │
    └── newsletter_ai.generate_newsletter() → Gemini ×1
```

### 4-2. 이상적인 병렬 구조 (개선 방향)

```
orchestrator.run_pipeline()
    │
    ├── [ThreadPoolExecutor or asyncio.gather]
    │   ├── Thread A: intent_ai()    → intent_type
    │   └── Thread B: cluster_ai()  → clusters
    │       (둘 다 완료 대기)
    │       format_ai(intent_type)  → format_style (즉시)
    │
    ├── [asyncio.gather 또는 ProcessPoolExecutor]
    │   ├── 주제1: selector → analyzer  (Gemini ×6)
    │   ├── 주제2: selector → analyzer  (Gemini ×6)
    │   └── 주제3: selector → analyzer  (Gemini ×6)
    │   (병렬 실행 — 단, Gemini 무료 RPM 제한 주의)
    │
    └── newsletter_ai(모든 분석 결과)
```

**⚠️ 병렬화 제약**: Gemini 무료 티어는 RPM(분당 요청수) 제한이 있어 병렬 호출 시 429 에러 발생 가능. 주제 3개를 동시에 돌리면 18회 동시 요청 → 제한 초과.

**실용적 해결책**: 주제 2개까지만 병렬, 영상별 analyzer는 내부적으로 이미 ThreadPoolExecutor 사용 중.

---

## 5. DB 설계 현황 및 보완점

### 5-1. 현재 테이블 구조

```sql
-- users
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_id           VARCHAR(255) UNIQUE NOT NULL,  -- PK로 사용
    email               VARCHAR(255) UNIQUE NOT NULL,
    delivery_type       VARCHAR(10) DEFAULT 'email',
    initial_intent      VARCHAR(20),                   -- '유희형'|'지식형'|'구매형'
    interest_categories TEXT,                          -- JSON 문자열
    send_time           VARCHAR(5) DEFAULT '21:00',    -- 'HH:MM'
    created_at          DATETIME
);

-- behavior_logs
CREATE TABLE behavior_logs (
    id          UUID PRIMARY KEY,
    user_id     VARCHAR(255),   -- = google_id
    event_type  VARCHAR(10),    -- 'search' | 'watch'
    keyword     VARCHAR(255),
    video_id    VARCHAR(50),
    logged_at   DATETIME
);

-- newsletters
CREATE TABLE newsletters (
    id           UUID PRIMARY KEY,
    user_id      VARCHAR(255),
    subject      VARCHAR(500),
    content_json TEXT,          -- 뉴스레터 전체 JSON
    delivered_at DATETIME,
    delivery_type VARCHAR(10)
);
```

### 5-2. DB 설계 보완 필요 항목

#### ① 구독/구독해지 상태 컬럼 부재
```sql
-- users 테이블에 추가 필요
ALTER TABLE users ADD COLUMN is_subscribed BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN unsubscribed_at DATETIME NULL;
```
현재는 DB에 있는 모든 유저에게 발송 — 수신 거부 수단 없음.

#### ② 구독 채널 테이블 미구현
```sql
-- 신규 생성 필요
CREATE TABLE subscriptions (
    id          UUID PRIMARY KEY,
    user_id     VARCHAR(255),
    channel_id  VARCHAR(100),
    channel_name VARCHAR(255),
    created_at  DATETIME
);
```
현재 `_get_subscribed_channel_ids()`가 빈 리스트 반환 — 구독 채널 personalization 미작동.

#### ③ 뉴스레터 읽음 확인 없음
```sql
-- newsletters 테이블에 추가 또는 별도 테이블
ALTER TABLE newsletters ADD COLUMN is_read BOOLEAN DEFAULT FALSE;
ALTER TABLE newsletters ADD COLUMN read_at DATETIME NULL;
```

#### ④ behavior_logs 인덱스 없음
```sql
-- 배치마다 전체 스캔 — 유저 수 늘수록 느려짐
CREATE INDEX idx_behavior_logs_user_date
  ON behavior_logs(user_id, logged_at);
```

#### ⑤ interest_categories JSON 스키마 정의 부재
현재: `"[\"파이썬\", \"머신러닝\"]"` 형태의 단순 문자열 배열  
개선 필요: 각 카테고리에 가중치 부여  
```json
[
  { "name": "파이썬", "weight": 0.8, "source": "history" },
  { "name": "머신러닝", "weight": 0.6, "source": "manual" }
]
```

---

## 6. 두 파이프라인 협력 구조 분석

### 6-1. 공유 레이어

```
Pipeline A                    Pipeline B
(라이브 서치)                 (뉴스레터 배치)
     │                              │
     └──── selector_ai ────────────┘
     └──── analyzer_ai ────────────┘
     (YouTube API + Gemini 공유)

단, 캐시는 분리:
- Pipeline A: _search_analysis_cache (인메모리, 서버 재시작 시 초기화)
- Pipeline B: 없음 (매 배치마다 새로 분석)
```

### 6-2. 데이터 흐름 충돌 지점

| 지점 | 현황 | 위험 |
|------|------|------|
| Gemini API 호출 | A와 B 동시 실행 시 공유 | 429 에러 가능 |
| YouTube API quota | 일 10,000유닛 공유 | 동시 사용자 多 시 초과 |
| _search_analysis_cache | 단일 dict (thread-safe 아님) | 동시 쓰기 race condition |

**해결 방안**:
```python
# main.py에 asyncio.Lock 적용
_cache_lock = asyncio.Lock()

async with _cache_lock:
    if keyword not in _search_analysis_cache:
        _search_analysis_cache[keyword] = result
```

### 6-3. 두 파이프라인이 같은 키워드를 처리할 때

예: 사용자가 "파이썬" 검색 → Pipeline A 캐시 저장  
   같은 날 저녁 배치 → Pipeline B도 "파이썬" 토픽 처리

현재는 Pipeline B가 Pipeline A 캐시를 활용하지 않음. 개선하면:
```python
# orchestrator.py - selector_ai 전에 캐시 확인
from main import _search_analysis_cache

if topic in _search_analysis_cache:
    analysis = _search_analysis_cache[topic]
else:
    # 새로 분석
```
→ Gemini 호출 절약 + 응답 시간 단축

---

## 7. 사용자 설정 분기 (send_time) 로직 분석

### 7-1. 현재 구현

```
scheduler.start_scheduler()
    │
    ├── morning_batch() ── CronTrigger(hour=8, minute=0)  → "08:00" 유저
    └── evening_batch() ── CronTrigger(hour=21, minute=0) → "21:00" 유저

_run_batch_for_send_time("08:00"):
  SELECT * FROM users WHERE send_time = '08:00'
  → 해당 유저들만 처리

_run_batch_for_send_time("21:00"):
  SELECT * FROM users WHERE send_time = '21:00'
  → 해당 유저들만 처리
```

### 7-2. 보완 필요 사항

**① 커스텀 send_time 지원 안 됨**

현재: 08:00 or 21:00 두 가지만  
PPT: 사용자가 원하는 시간 설정 가능  

해결안: 동적 스케줄러 또는 매분 체크 방식
```python
# 매 분 실행하는 단일 배치
@scheduler.scheduled_job(CronTrigger(minute='*'))
async def per_minute_batch():
    now = datetime.now(timezone('Asia/Seoul'))
    current_time = now.strftime("%H:%M")
    await _run_batch_for_send_time(current_time)
```

**② send_time 기본값(21:00)인 유저 처리**

현재: `send_time IS NULL`인 유저는 배치에서 누락됨  
수정: `WHERE send_time = '21:00' OR send_time IS NULL`

**③ 발송 중복 방지**

같은 날 이미 발송한 유저에게 재발송 방지 로직 없음.
```sql
-- newsletters 테이블에서 오늘 발송 여부 확인
SELECT COUNT(*) FROM newsletters
WHERE user_id = ? AND DATE(delivered_at) = CURDATE()
```

---

## 8. 대시보드 구현 로직 (필요한 API 설계)

### 8-1. 대시보드가 필요로 하는 API (현재 없는 것)

```
GET /my/profile
  → { email, send_time, initial_intent, interest_categories }

PUT /my/profile
  → body: { send_time?, email?, interest_categories? }

GET /my/stats
  → {
      today_log_count: 12,
      triggered_topics: ["파이썬", "React"],
      profile_categories: ["개발", "AI"],
      merged_topics: ["파이썬", "React", "개발", "AI"],
      total_newsletters: 14,
      last_newsletter_at: "2024-04-18T21:00:00"
    }

DELETE /my/subscription
  → 수신 해지 (users.is_subscribed = False)

GET /my/newsletter/{newsletter_id}
  → content_json 전체 반환 (상세 보기)
```

### 8-2. 이상적인 대시보드 화면 구성

```
┌─────────────────────────────────────────────────────┐
│  ✦ Tubify              규리 (sophia.gyuri@gmail.com) │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌── 오늘 활동 ──────────────────────────────────┐  │
│  │  검색 8회 · 시청 4회 · 트리거 주제 3개        │  │
│  │  ─────────────────────────────────────────   │  │
│  │  트리거: [파이썬] [머신러닝] [React]          │  │
│  │  프로필: [개발] [AI] [스타트업]               │  │
│  │  → 오늘 발송 예정 키워드: 6개 합산            │  │
│  └────────────────────────────────────────────────┘  │
│                                                     │
│  ┌── 뉴스레터 히스토리 ─────────────────────────┐  │
│  │  [2024-04-19 21:00] 🧠 파이썬 생태계 동향     │  │
│  │  [2024-04-18 21:00] 🛒 맥북 프로 vs 델 비교   │  │
│  │  [2024-04-17 08:00] 😄 유튜브 숏츠 트렌드     │  │
│  └────────────────────────────────────────────────┘  │
│                                                     │
│  ┌── 내 설정 ─────────────────────────────────────┐  │
│  │  발송 시간: [오전 8시 ▼] → [저장]             │  │
│  │  이메일: sophia.gyuri@gmail.com [변경]         │  │
│  │  성향: [지식형 🧠] [유희형 😄] [구매형 🛒]    │  │
│  │  관심사: [파이썬] [머신러닝] [+추가]           │  │
│  │                              [수신 해지]       │  │
│  └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## 9. 보완해야 할 점 (우선순위순)

### 🔴 Critical (서비스 정상 작동에 필요)

| # | 항목 | 파일 | 내용 |
|---|------|------|------|
| 1 | send_time NULL 유저 배치 누락 | scheduler.py | `send_time IS NULL` → 21:00 기본 처리 |
| 2 | 수신 해지 수단 없음 | DB, main.py | is_subscribed 컬럼 + DELETE /my/subscription |
| 3 | 발송 중복 방지 없음 | scheduler.py | 오늘 이미 발송한 유저 스킵 로직 |
| 4 | _search_analysis_cache thread-safety | main.py | asyncio.Lock 적용 |
| 5 | resend pip 의존성 누락 | requirements.txt | `resend` 패키지 추가 확인 |

### 🟠 High (UX에 직접 영향)

| # | 항목 | 파일 | 내용 |
|---|------|------|------|
| 6 | Side Panel 자동 갱신 없음 | side_panel.html | 탭 URL 변경 감지 → 재분석 |
| 7 | 대시보드 설정 변경 UI 없음 | dashboard.html | GET/PUT /my/profile 연동 |
| 8 | 온보딩 완료 후 리다이렉트 없음 | onboarding.html | Step 3 완료 → dashboard.html 이동 |
| 9 | 로그 투명성 UI 없음 | dashboard.html | /my/logs 결과를 대시보드에 표시 |
| 10 | 뉴스레터 상세 보기 없음 | dashboard.html | 카드 클릭 → content_json 전체 렌더링 |

### 🟡 Medium (완성도)

| # | 항목 | 파일 | 내용 |
|---|------|------|------|
| 11 | Pipeline A↔B 캐시 공유 | orchestrator.py | A 캐시를 B에서 재활용 |
| 12 | 구독 채널 DB 미구현 | database.py, scheduler.py | subscriptions 테이블 + selector_ai 연동 |
| 13 | 인텐트 실시간 갱신 없음 | orchestrator.py | 클릭 패턴으로 intent_type 업데이트 |
| 14 | Chrome history 기간 90일→1년 | onboarding.html | maxResults 조정 |
| 15 | 커스텀 send_time | scheduler.py | 매분 체크 방식으로 변경 |

### 🟢 Nice-to-have (고도화)

| # | 항목 | 내용 |
|---|------|------|
| 16 | 주제별 병렬 처리 | Gemini RPM 한도 안에서 병렬화 |
| 17 | 뉴스레터 읽음 추적 | 이메일 픽셀 트래킹 or 클릭 추적 |
| 18 | 푸시 알림 | 뉴스레터 발송 완료 시 브라우저 알림 |
| 19 | A/B 테스트 | 의도 타입별 뉴스레터 CTR 비교 |

---

## 10. 남은 구현 항목 체크리스트

### Backend

```
[ ] users 테이블: is_subscribed 컬럼 추가
[ ] subscriptions 테이블 생성 + CRUD
[ ] GET /my/profile — 프로필 조회
[ ] PUT /my/profile — 발송시간/관심사/이메일 수정
[ ] GET /my/stats — 오늘 활동 + 뉴스레터 통계
[ ] GET /my/newsletter/{id} — 뉴스레터 상세
[ ] DELETE /my/subscription — 수신 해지
[ ] scheduler: send_time NULL 처리 + 중복 발송 방지
[ ] main.py: _search_analysis_cache asyncio.Lock
[ ] requirements.txt: resend 패키지 확인
```

### Frontend (dashboard.html 대대적 개편)

```
[ ] 오늘 활동 섹션 (GET /my/logs 연동)
[ ] 뉴스레터 히스토리 → 상세 모달
[ ] 내 설정 섹션 (send_time, interest_categories 편집)
[ ] 수신 해지 버튼
```

### Extension

```
[ ] side_panel.html: 탭 URL 변경 감지 → 자동 재분석
[ ] popup.js: 오늘 로그 수 / 트리거 주제 표시
[ ] onboarding.html: chrome.history maxResults 확대 (90일 → 1년 분량)
[ ] onboarding.html: 온보딩 완료 후 dashboard.html 리다이렉트
```

---

## 11. 우선순위 로드맵

```
Week 1 — 안정화 (Critical 수정)
├── scheduler send_time NULL 처리
├── 발송 중복 방지
├── is_subscribed 컬럼 + 해지 API
└── cache thread-safety

Week 2 — UX 완성 (High 항목)
├── dashboard.html 전면 개편
│   ├── GET /my/stats 연동 (오늘 활동)
│   ├── GET /my/logs 연동 (로그 투명성)
│   ├── PUT /my/profile 연동 (설정 변경)
│   └── 뉴스레터 상세 모달
├── side_panel: 탭 변경 자동 갱신
└── onboarding: 완료 후 대시보드 이동

Week 3 — 고도화 (Medium 항목)
├── subscriptions 테이블 + 구독 채널 personalization
├── Pipeline A↔B 캐시 공유
└── 커스텀 send_time (매분 배치)
```

---

## 12. 핵심 개선 요약 (3줄 요약)

1. **배치 안정성**: send_time NULL 처리 + 중복 발송 방지 + 수신 해지 — 이 3개가 서비스 운영의 최소 조건
2. **대시보드 부재**: 사용자가 자신의 데이터(로그, 관심사, 히스토리)를 볼 수 없음 — /my/* API군과 dashboard.html 개편이 UX의 핵심
3. **Pipeline A 독립성 강화**: Side Panel이 탭 전환을 감지하지 못함 — 실사용 시 가장 먼저 체감되는 버그
