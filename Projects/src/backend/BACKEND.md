# Tubify — BACKEND.md

백엔드 팀원 공유용 기술 문서. API 명세, DB 구조, AI 파이프라인 상세.

---

## 주의사항 (먼저 읽기)

- `preprocessing.py` **수정 금지** (팀원 코드)
- `user_id`는 항상 `google_id` 문자열 기준 — `users.id` (UUID) 절대 혼용 금지
- `google.generativeai` 직접 import 금지 → `agents/gemini_client.py`의 `call_gemini()`만 사용
- Gemini 무료 티어 하루 20회 제한 → 테스트 최소화
- `datetime.utcnow()` 사용 금지 → `datetime.now(timezone.utc)` 사용
- ChromaDB, RAG 방식 사용 금지
- 서버 재시작 시 OAuth credentials + `_search_analysis_cache` 초기화됨 → 재로그인 필요

---

## API 엔드포인트

### 인증

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/auth/login` | Google OAuth + PKCE 로그인 시작 |
| GET | `/auth/callback` | 로그인 완료 후 JWT 발급 |
| GET | `/auth/me` | 현재 로그인 사용자 확인 (JWT 필요) |

### 행동 수집

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/collect` | 검색/시청 이벤트 수집 (JWT 필요) |
| GET | `/collect/today` | 오늘 로그 + 트리거 주제 (JWT 필요) |
| GET | `/my/logs?limit=50` | 내 행동 로그 투명성 — triggered + profile + merged 반환 (JWT 필요) |

`/collect` 요청 예시:
```json
{ "event_type": "search", "keyword": "파이썬 강의", "video_id": null }
```

### 즉석 검색 분석 (Pipeline A)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/analyze_search?keyword=xxx` | selector_ai + analyzer_ai 즉시 실행 (JWT 필요) |

> 동일 키워드 재호출 시 `_search_analysis_cache` 반환 (Gemini 생략)

### 구독 설정

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/subscribe` | 이메일 + 발송 시간 저장 (JWT 필요) |
| GET | `/subscriptions` | 유튜브 구독 채널 목록 (JWT 필요) |

### 프로필

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/profile/init` | 온보딩 완료 시 관심사 + 의도 저장 (JWT 필요) |
| POST | `/profile/analyze-history` | chrome.history 키워드 → 관심사 추론 (JWT 필요) |

### 뉴스레터

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/newsletter/history` | 내 뉴스레터 히스토리 (JWT 필요) |
| POST | `/newsletter/send-now` | 즉시 발송 테스트 (JWT 필요) |

### 관리자 (ADMIN_SECRET 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/admin/users` | 전체 유저 목록 |
| GET | `/admin/logs` | 오늘 전체 행동 로그 |
| POST | `/admin/pipeline/run?user_id=xxx` | 특정 유저 파이프라인 즉시 실행 |

### Swagger 사용법

```
1. 로그인 후 주소창: http://localhost:8000/onboarding.html?token=eyJ...
2. token= 뒤 값 복사
3. http://localhost:8000/docs → 우측 상단 Authorize → 토큰 붙여넣기
```

---

## DB 명세

엔진: PostgreSQL / ORM: SQLAlchemy asyncpg

### users
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK (내부용, API에서 사용 안 함) |
| google_id | VARCHAR(255) | 실질적 PK — 모든 FK 기준 |
| email | VARCHAR(255) | 이메일 |
| delivery_type | VARCHAR(10) | 'email' |
| initial_intent | VARCHAR(20) | '유희형'\|'지식형'\|'구매형' |
| interest_categories | TEXT | JSON 문자열 배열 |
| send_time | VARCHAR(5) | 'HH:MM' (기본 '21:00') |
| created_at | DateTime | 가입 시각 |

### behavior_logs
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| user_id | VARCHAR(255) | = google_id |
| event_type | VARCHAR(10) | 'search'\|'watch' |
| keyword | VARCHAR(500) | 검색어 또는 영상 제목 |
| video_id | VARCHAR(50) | nullable |
| logged_at | DateTime | 수집 시각 |

### newsletters
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| user_id | VARCHAR(255) | = google_id |
| subject | VARCHAR(500) | 이메일 제목 |
| content_json | TEXT | newsletter_ai 전체 출력 JSON |
| delivered_at | DateTime | 발송 시각 |
| delivery_type | VARCHAR(10) | 'email' |

### DB 직접 확인

pgAdmin 권장. 또는 psql:
```bash
chcp 65001  # Windows 인코딩
psql -U postgres -d techvisibility
```
```sql
SELECT * FROM users;
SELECT * FROM behavior_logs ORDER BY logged_at DESC LIMIT 10;
SELECT * FROM newsletters ORDER BY delivered_at DESC LIMIT 10;
```

---

## AI 파이프라인

### Gemini 호출 방법

```python
from agents.gemini_client import call_gemini, parse_section, parse_bullet_list

text = call_gemini(prompt, temperature=0.3)
summary = parse_section(text, "요약")
items = parse_bullet_list(text, "핵심주장")
```

`google.generativeai` 직접 import는 `gemini_client.py` 내부에서만. 다른 파일에서 절대 금지.

### Pipeline A — 라이브 서치

```
/analyze_search?keyword=xxx
→ selector_ai (YouTube API, Gemini 0회)
→ analyzer_ai (Gemini 최대 6회: 영상 5개×1 + 교차분석 1)
→ _search_analysis_cache 저장
→ JSONResponse 반환
```

DB 저장 없음. 인메모리 캐시만.

### Pipeline B — 뉴스레터 배치

```
scheduler._run_batch_for_send_time(HH:MM)
→ users WHERE send_time = HH:MM 조회
→ get_today_logs + _get_profile_keywords → _merge_keywords (최대 10개)
→ asyncio.to_thread(run_pipeline)
   → intent_ai (1회) → format_ai (0회)
   → cluster_ai (1회)
   → selector_ai + analyzer_ai × 주제 수 (최대 6회/주제)
   → newsletter_ai (1회)
→ newsletters INSERT
→ Resend 이메일 발송
```

**Gemini 호출 수 (주제 1개 기준)**: 최대 9회
**무료 티어 하루 20회** → 주제 2개까지 안전

### 에이전트별 INPUT/OUTPUT

**intent_ai**
- IN: `triggered_topics: List[str]`, `clicked_video_titles: List[str]`
- OUT: `{"intent_type": "유희형"|"지식형"|"구매형"}`
- Gemini: 1회 (temperature=0.1)

**format_ai**
- IN: `intent_type: str`
- OUT: `{"tone": str, "structure": str, "length": "short"|"long"}`
- Gemini: 0회 (규칙 기반)

**cluster_ai**
- IN: `raw_keywords: List[str]`
- OUT: `[{"topic": str, "keywords": List[str]}]`
- Gemini: 1회 (temperature=0.2)

**selector_ai**
- IN: `topic: str`, `subscribed_channel_ids: List[str]`
- OUT: `List[Dict]` 상위 5개 (점수 내림차순)
- Gemini: 0회 (YouTube API)
- ViewRate = `norm_view_rate×0.5 + is_subscribed×0.3 + recency_score×0.2`
- 쇼츠(60초 이하) 자동 제거

**analyzer_ai**
- IN: `keyword: str`, `videos: List[Dict]`
- OUT: `{"keyword", "videos": [...], "common_facts": [...], "controversies": [...]}`
- Gemini: 최대 6회 (영상당 1회 + 교차분석 1회)
- 병렬 처리: `ThreadPoolExecutor(max_workers=5)`
- `ad_score >= 60` → `ad_detected = True` → 출처 제외

**newsletter_ai**
- IN: `user_id`, `analyses: List[Dict]`, `delivery_type`, `format_style: Dict`, `intent_type: str`
- OUT: `{"subject", "intent_type", "topics": [{"topic", "summary", "pros", "cons", "sources"}]}`
- Gemini: 주제당 1회

---

## 스케줄러

```
08:00 KST → morning_batch() → send_time='08:00' 유저
21:00 KST → evening_batch() → send_time='21:00' 유저
1시간마다 → check_new_videos() (TODO: 구독 채널 새 영상 감지)
```

스케줄러는 `main.py` lifespan에서 `start_scheduler()` / `stop_scheduler()` 호출.

---

## 크롬 익스텐션 인증 흐름

```
웹사이트 로그인 → JWT 발급
→ onboarding.html이 chrome.runtime.sendMessage로 JWT 전달
→ background.js가 chrome.storage.local에 저장
→ content.js가 /collect 호출 시 JWT 사용
→ side_panel.html이 URL 파라미터로 JWT 수신
```

---

## 429 에러 발생 시 (Gemini 한도 초과)

1. Google AI Studio에서 새 프로젝트 생성
2. 새 API 키 발급
3. `.env`의 `GEMINI_API_KEY` 교체
4. 한국 시간 오후 4시에 일일 한도 리셋
