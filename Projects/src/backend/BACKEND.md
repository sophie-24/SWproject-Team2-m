# Tubify — BACKEND.md

백엔드 팀원 공유용 기술 문서. API 명세, DB 구조, AI 파이프라인 상세.
최종 업데이트: 2026-05-19 (Issue 7까지 반영)

---

## 주의사항

- 서버 재시작 시 OAuth credentials 메모리 캐시 초기화됨 → DB fallback으로 자동 복원 (로그인 유지)
- `_search_analysis_cache` 재시작 시 초기화 → 재분석 필요
- `send_time` DB 저장: JSON 배열 `["21:00"]` / API 입출력: 단일 문자열 `"21:00"`
- 하트 관심 토픽 조회 시 반드시 `UserInterest.is_active == True` 조건 포함
- `preprocessing.py`, `transcript_service.py` 수정 시 주의 ⚠️

---

## Swagger UI 사용법

```
1. 브라우저에서 http://localhost:8000/auth/login → Google 로그인
2. 리다이렉트된 URL의 ?token= 이후 값 복사
3. http://localhost:8000/docs 접속
4. 우측 상단 Authorize 버튼 → 토큰 붙여넣기 → Authorize
5. 원하는 엔드포인트 클릭 → "Try it out" → Execute
```

---

## API 엔드포인트 전체 목록

### 인증 (JWT 불필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/auth/login` | Google OAuth + PKCE 로그인 시작 → 리다이렉트 |
| GET | `/auth/callback` | 로그인 완료 후 JWT 발급 → 온보딩/대시보드로 이동 |
| GET | `/auth/me` | 현재 로그인 사용자 확인 (JWT 필요) |
| GET | `/auth/extension-done` | 익스텐션 팝업 로그인 완료 자동 닫힘 |

### 프로필 (JWT 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/my/profile` | 이메일·send_time·initial_intent·interest_categories·**interests(하트토픽)** 반환 |
| PUT | `/my/profile` | send_time 단일문자열 + interest_categories 수정 |
| GET | `/my/stats` | 오늘 활동 통계 — 로그 수·트리거 토픽·뉴스레터 수 |
| GET | `/my/settings` | 구독 설정 조회 — send_time·is_subscribed·delivery_type |
| PATCH | `/settings/send_time` | 발송 시간 변경 `{ "send_time": "21:00" }` |
| PATCH | `/my/send-time` | `/settings/send_time` 별칭 |

### 온보딩 (JWT 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/profile/init` | 온보딩 완료 — initial_intent + interest_categories 저장 |
| POST | `/profile/analyze-history` | chrome.history 키워드 → Gemini 관심사 추론 + 저장 |
| POST | `/subscribe` | 이메일 + send_time 저장 |

### 하트 관심 토픽 (JWT 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/interests` | 활성 관심 토픽 목록 + video_count 반환 |
| POST | `/interests` | 관심 토픽 추가 (최대 5개) — `{ "title": "영상제목", "video_id": "abc" }` |
| DELETE | `/interests/{topic}` | 관심 토픽 취소 (soft delete — is_active=False) |
| GET | `/interests/unsubscribe-confirm` | 메일 내 관심 취소 링크 진입점 (Issue 5 — 미구현) |

### 구독 설정 (JWT 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/my/subscription` | 뉴스레터 수신 동의 |
| DELETE | `/my/subscription` | 수신 거부 (is_subscribed=False) |
| DELETE | `/my/withdraw` | 회원 탈퇴 (users 행 삭제 + CASCADE) |

### AI 분석 (JWT 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/analyze_search?keyword=xxx` | Pipeline A — 실시간 검색 분석 (캐시 활용) |
| POST | `/analyze_video` | 단일 영상 분석 + 관심 토픽 연결 — `{ "video_id": "xxx", "title": "제목" }` |
| GET | `/ai_analyze/{video_id}` | 단일 영상 상세 분석 (query 파라미터) |

### 뉴스레터 (JWT 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/newsletter/history` | 내 뉴스레터 발송 히스토리 |
| POST | `/newsletter/send-now` | 즉시 발송 테스트 (스케줄러 없이) |

### YouTube (JWT 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/subscriptions` | 유튜브 구독 채널 목록 조회 |
| GET | `/search?keyword=xxx` | YouTube 영상 검색 |

### 행동 수집 — DEPRECATED (JWT 필요)

> Issue 8에서 제거 예정. 현재는 수집만 됨 — 뉴스레터 발송에 사용 안 함.

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/collect` | 검색/시청 이벤트 수집 |
| GET | `/collect/today` | 오늘 로그 + 트리거 주제 |
| GET | `/my/logs` | 내 행동 로그 투명성 |
| GET | `/my/interests` | 누적 관심사 weight 랭킹 (behavior 기반) |

### 자막 / 전처리

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/transcript/{video_id}` | 자막 텍스트 조회 |
| GET | `/transcript/available/{video_id}` | 가용 자막 언어 목록 |
| GET | `/preprocess/{video_id}` | 자막 청크 변환 |

### 관리자 (Admin-Secret 헤더 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/admin/users` | 전체 유저 목록 |
| GET | `/admin/logs` | 오늘 전체 행동 로그 |
| POST | `/admin/pipeline/run?user_id=xxx` | 특정 유저 Pipeline B 즉시 실행 |

---

## DB 명세

엔진: PostgreSQL / ORM: SQLAlchemy asyncpg

### users

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK (내부용) |
| google_id | VARCHAR(255) | 실질적 PK — 모든 FK 기준 |
| email | VARCHAR(255) | 이메일 |
| delivery_type | VARCHAR(10) | 'email' |
| initial_intent | VARCHAR(20) | '유희형'\|'지식형'\|'구매형' |
| interest_categories | TEXT | JSON 문자열 배열 (온보딩 캐시) |
| send_time | TEXT | JSON 배열 `["21:00"]` — API는 단일 string 반환 |
| is_subscribed | BOOLEAN | 수신 동의 여부 |
| oauth_credentials | TEXT | Google OAuth JSON (서버 재시작 후 복원용) |
| subscribed_channels | TEXT | DEPRECATED — 유튜브 구독 채널 ID 캐시 |
| created_at | DateTime | 가입 시각 |

### user_interests

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| user_id | VARCHAR(255) | = google_id |
| category | VARCHAR(100) | 사용자에게 보여줄 토픽명 |
| normalized_topic | VARCHAR(100) | 중복 판단 기준 (소문자·공백 정규화) |
| source | ENUM | 'manual'(하트)\|'onboarding'\|'behavior'(deprecated) |
| is_active | BOOLEAN | soft delete — False이면 취소 상태 |
| weight | INTEGER | 하위 호환 (더 이상 누적 안 함) |
| created_at | DateTime | 최초 하트 시각 |

UniqueConstraint: `(user_id, normalized_topic)`, `(user_id, category)`

### user_interest_videos

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| user_interest_id | UUID | FK → user_interests.id (CASCADE 삭제) |
| video_id | VARCHAR(50) | YouTube video_id |
| title | TEXT | 영상 제목 (참고용) |
| created_at | DateTime | 연결 시각 |

### newsletters

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID | PK |
| user_id | VARCHAR(255) | = google_id |
| subject | VARCHAR(500) | 이메일 제목 |
| content_json | TEXT | newsletter_ai 전체 출력 JSON |
| delivered_at | DateTime | 발송 시각 |
| delivery_status | ENUM | 'generated'\|'sent'\|'failed' |
| error_message | TEXT | 발송 실패 사유 |

### behavior_logs / report_batches

> **DEPRECATED** — Issue 8에서 제거 예정. 뉴스레터 발송에 더 이상 사용 안 함.

---

## Pipeline B 발송 흐름 (현재)

```
scheduler.per_minute_batch()
  → users WHERE is_subscribed=True AND send_time 일치
  → UserInterest WHERE is_active=True (하트 관심 토픽)
  → 0개이면 skip (BehaviorLog fallback 없음)
  → run_pipeline(raw_keywords=topics, skip_clustering=True)
     → intent_ai → selector_ai × 주제 수 → analyzer_ai × 주제 수 → newsletter_ai
  → newsletters 저장
  → Resend 이메일 발송
```

`skip_clustering=True`: 하트 토픽은 이미 정제됨 → cluster_ai 건너뜀

---

## 에러 대응

### 429 에러 (Gemini 한도 초과)

1. Google AI Studio에서 새 프로젝트 생성
2. 새 API 키 발급
3. `.env`의 `GEMINI_API_KEY` 교체
4. 한국 시간 오후 4시에 일일 한도 리셋

### DB 마이그레이션 (컬럼 추가 시)

SQLAlchemy `init_db()`는 새 컬럼 자동 추가 안 함. `schema.sql` 하단 마이그레이션 SQL을 pgAdmin에서 직접 실행.

```sql
-- 예: user_interests에 normalized_topic 추가
ALTER TABLE user_interests ADD COLUMN IF NOT EXISTS normalized_topic VARCHAR(100);
ALTER TABLE user_interests ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
```
