# Tubify — BACKEND.md

백엔드 팀원 공유용 기술 문서. API 명세, DB 구조, AI 파이프라인 상세.

---

## 주의사항
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

## 429 에러 발생 시 (Gemini 한도 초과)

1. Google AI Studio에서 새 프로젝트 생성
2. 새 API 키 발급
3. `.env`의 `GEMINI_API_KEY` 교체
4. 한국 시간 오후 4시에 일일 한도 리셋
