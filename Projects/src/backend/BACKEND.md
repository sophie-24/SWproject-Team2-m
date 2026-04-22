## 실행 방법

### 1. 패키지 설치

```bash
cd Projects/src/backend
pip install -r requirements.txt
pip install yt-dlp
```

### 2. 환경변수 설정

`Projects/src/backend/` 안에 `.env` 파일 생성:

```
GOOGLE_CLIENT_ID=발급받은_클라이언트_ID
GOOGLE_CLIENT_SECRET=발급받은_클라이언트_시크릿
REDIRECT_URI=http://localhost:8000/auth/callback
YOUTUBE_API_KEY=발급받은_유튜브_API_키
GEMINI_API_KEY=발급받은_Gemini_API_키
JWT_SECRET=랜덤_문자열
DATABASE_URL=postgresql+asyncpg://postgres:비밀번호@localhost:5432/techvisibility
FRONTEND_URL=http://localhost:8000
RESEND_API_KEY=re_xxxxxxxx                    # Resend 대시보드에서 발급
RESEND_FROM_EMAIL=curator@tubify.com          # 발신자 주소 (기본값)
ADMIN_SECRET=관리자_시크릿_문자열
```

> JWT_SECRET 생성: `python -c "import secrets; print(secrets.token_hex(32))"`
> `.env` 파일은 톡으로 받은 거 설정해서 gitignore 처리하고 커밋하지 말기.

### PostgreSQL DB 생성

```bash
psql -U postgres
CREATE DATABASE techvisibility;
\q
```

> 테이블은 서버 시작 시 자동 생성됨

### 3. 서버 실행

```bash
uvicorn main:app --reload --port 8000
```

서버 주소: `http://localhost:8000`
API 문서: `http://localhost:8000/docs`

> 프론트엔드도 `http://localhost:8000`에서 같이 서빙됨. Live Server 불필요.

### 4. 크롬 익스텐션 로드

1. Chrome 주소창에 `chrome://extensions` 입력
2. 우측 상단 **개발자 모드** 활성화
3. **압축 해제된 확장 프로그램 로드** 클릭
4. `Projects/src/extension` 폴더 선택
5. 익스텐션 ID 확인 → `extension/background.js`의 `EXTENSION_ID`에 입력

---

## AI 파이프라인

두 가지 독립 파이프라인이 존재한다. orchestrator는 **Pipeline B(뉴스레터)에서만** 사용한다.

### Pipeline A — 라이브 서치 (실시간 즉석 분석, 메인)

```
[팝업 / 플로팅 버튼 클릭]
↓
background.js → chrome.sidePanel.open()
↓
side_panel.html (Chrome Side Panel)
↓
GET /analyze_search?keyword=xxx  (JWT 필요)
↓
selector_ai   영상 후보 선정 (상위 5개, ViewRate×개인화 공식)
↓
analyzer_ai   자막 분석 + 광고 탐지 + 교차 분석
↓
_search_analysis_cache 저장 (동일 키워드 재호출 시 Gemini 생략)
↓
side_panel.html 렌더링 (영상 카드, 공통사실, 쟁점)
```

**Gemini 호출 수: 최대 6회** / orchestrator · cluster_ai · intent_ai · newsletter_ai 사용 안 함

### Pipeline B — 뉴스레터 (배치 발송, 서브)

```
[수집] 익스텐션 → /collect → behavior_logs DB 저장
↓
[합산] 오늘 로그(triggered_topics) + 온보딩 프로필(interest_categories) → merged_topics
↓
[스케줄] 08:00 또는 21:00 KST (users.send_time 기준)
[orchestrator.run_pipeline()]
↓
Step 0  intent_ai     검색 의도 분류 (유희형 / 지식형 / 구매형)
          ↓
        format_ai     의도 타입 → 뉴스레터 스타일 결정 (Gemini 호출 없음)
          ↓
Step 1  cluster_ai    키워드 의미 단위 클러스터링
          ↓
Step 2  selector_ai   주제별 영상 후보 선정 (ViewRate×개인화 기반 상위 5개)
          ↓
Step 3  analyzer_ai   자막 분석 + 광고 탐지 + 교차 분석
          ↓
Step 4  newsletter_ai 의도 맞춤 뉴스레터 생성
          ↓
[DB 저장] newsletters 테이블
          ↓
[발송] Resend API (curator@tubify.com)
```

**Gemini 호출 수 (주제 1개 기준): 최대 9회**

> 무료 티어 하루 20회 제한 → 뉴스레터 1주제 + 검색 분석 1회면 15회 소모

---

## API 엔드포인트

### 헬스체크

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 확인 |

### 인증

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/auth/login` | 구글 OAuth + PKCE 로그인 시작 |
| GET | `/auth/callback` | 로그인 완료 후 JWT 발급 |
| GET | `/auth/me` | 현재 로그인 사용자 확인 (JWT 필요) |

### 행동 수집 (익스텐션 → 백엔드)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/collect` | 검색/시청 이벤트 수집 (JWT 필요) |
| GET | `/collect/today` | 오늘 수집된 로그 + 트리거 주제 확인 (JWT 필요) |
| GET | `/my/logs?limit=50` | **내 행동 로그 투명성** — triggered+profile+merged 전체 반환 (JWT 필요) |

**`/collect` 요청 예시**
```json
{
  "event_type": "search",
  "keyword": "지성 피부 세럼",
  "video_id": null
}
```

### 즉석 검색 분석 Pipeline A ★

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/analyze_search?keyword=xxx` | selector_ai + analyzer_ai 즉시 실행 (JWT 필요) |

> keyword 기준 인메모리 캐시(`_search_analysis_cache`) — 동일 키워드 재호출 시 Gemini 생략

### 구독 설정

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/subscribe` | 수신 방법 설정 (users 테이블 실제 저장, JWT 필요) |
| GET | `/subscriptions` | 유튜브 구독 채널 목록 (JWT 필요) |

### 뉴스레터

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/newsletter/history` | 내 뉴스레터 히스토리 (JWT 필요) |
| POST | `/newsletter/send-now` | 즉시 발송 테스트 — DB 저장 포함 (JWT 필요) |

### 데이터

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/search?keyword=파이썬` | 키워드로 영상 검색 (YouTube API, Gemini 없음) |
| GET | `/transcript/{video_id}` | 영상 자막 + timestamp |
| GET | `/transcript/available/{video_id}` | 사용 가능한 자막 언어 목록 |
| GET | `/preprocess/{video_id}` | 자막 수집 → 정제 → 청크 분할 |

### 페이지

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/` | index.html |
| GET | `/onboarding.html` | 온보딩 페이지 |
| GET | `/dashboard.html` | 뉴스레터 히스토리 대시보드 |
| GET | `/search_dashboard.html` | 즉석 검색 분석 대시보드 ★ NEW |
| GET | `/admin.html` | 관리자 대시보드 |

### 관리자 (ADMIN_SECRET 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/admin/users` | 전체 유저 목록 |
| GET | `/admin/logs` | 오늘 전체 행동 로그 |
| POST | `/admin/pipeline/run?user_id=xxx` | 특정 유저 파이프라인 즉시 실행 |

---

## DB 테이블

| 테이블 | 설명 |
|--------|------|
| `users` | 유저 정보 (google_id, email, delivery_type) |
| `behavior_logs` | 익스텐션 수집 로그 (user_id = google_id) |
| `newsletters` | 발송된 뉴스레터 히스토리 (user_id = google_id) |

> ⚠️ `user_id` 기준: 모든 테이블에서 `google_id` 문자열 사용. `users.id`(UUID)와 혼용 금지.

**DB 직접 확인 (pgAdmin 권장):**
```sql
SELECT * FROM users;
SELECT * FROM behavior_logs ORDER BY logged_at DESC LIMIT 10;
SELECT * FROM newsletters ORDER BY delivered_at DESC LIMIT 10;
```

---

## 파일 구조

```
Projects/src/
│
├── backend/
│   ├── main.py                   # FastAPI 서버, lifespan 패턴
│   ├── auth.py                   # Google OAuth + PKCE + JWT
│   ├── database.py               # DB 연결 + 테이블 모델
│   ├── scheduler.py              # 배치 스케줄러 (매일 21:00 KST)
│   ├── preprocessing.py          # 자막 전처리 (수정 금지)
│   ├── transcript_service.py     # 자막 수집 (yt-dlp)
│   ├── youtube_search.py         # 키워드 영상 검색
│   ├── youtube_service.py        # 구독 채널 목록
│   │
│   ├── collector/
│   │   ├── behavior_store.py     # 행동 로그 저장 + 조회
│   │   └── trigger.py            # 2회 이상 주제 트리거 판단
│   │
│   ├── agents/
│   │   ├── gemini_client.py      # ★ Gemini 공통 클라이언트
│   │   ├── intent_ai.py          # 검색 의도 분류 (Pipeline A)
│   │   ├── format_ai.py          # 뉴스레터 포맷 결정 (Pipeline A)
│   │   ├── cluster_ai.py         # [AI 1] 주제 클러스터링 (Pipeline A)
│   │   ├── selector_ai.py        # [AI 2] 영상 선정 (Pipeline A + B 공유)
│   │   ├── analyzer_ai.py        # [AI 3] 자막 분석 (Pipeline A + B 공유)
│   │   ├── newsletter_ai.py      # [AI 4] 뉴스레터 생성 (Pipeline A)
│   │   └── orchestrator.py       # Pipeline A 총괄
│   │
│   └── delivery/
│       └── email.py              # 이메일 발송 (Resend API)
│
├── frontend/
│   ├── index.html                # 랜딩 페이지
│   ├── onboarding.html           # 온보딩 (수신 방법 설정)
│   ├── dashboard.html            # 뉴스레터 히스토리
│   ├── search_dashboard.html     # ★ 즉석 검색 분석 결과 페이지
│   └── admin.html                # 관리자 대시보드
│
└── extension/
    ├── manifest.json             # Manifest V3 (permissions: storage, activeTab, tabs, sidePanel)
    ├── background.js             # JWT 수신 + storage / sidePanel.open 중개
    ├── content.js                # 유튜브 플로팅 버튼 + /collect 행동 로그
    ├── popup.html                # 익스텐션 팝업 UI
    ├── popup.js                  # 검색 요약 + 사이드 패널 이동
    └── side_panel.html           # ★ Chrome Side Panel — Pipeline A 결과
```

---

## 주의사항

- 자막 수집을 위해 `cookies.txt` 파일이 `backend/` 폴더 안에 있어야 함 → 톡으로 직접 받은 거 넣기! (깃에 올리면 안 됨)
- 서버 재시작하면 OAuth credentials, `_search_analysis_cache` 초기화됨 → 재로그인 필요
- Gemini 무료 티어 하루 20회 제한 → 뉴스레터 1주제(9회) + 검색 분석(6회) = 15회
- `google.genai` 패키지 사용 금지 → `agents/gemini_client.py`의 `call_gemini()` 사용
- 새 AI 모듈 추가 시 `gemini_client.py` import 필수 — 모듈별 직접 genai 초기화 금지
- ChromaDB, RAG 방식 사용 금지
