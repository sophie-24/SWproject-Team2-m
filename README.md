# Tubify

> 멀티에이전트 기반 실시간 유튜브 정보 분석 및 메일링 서비스

유튜브 알고리즘은 내가 보고 싶은 걸 주는 게 아니라 계속 보게 만든다.
Tubify는 사용자가 직접 하트한 관심 토픽을 AI가 분석해 광고를 걸러내고, 핵심만 뉴스레터로 보내준다.

---

## 팀원

| 이름 | 전공 | 역할 | 주요 기여 내용 | GitHub |
|------|------|------|---------------|--------|
| 김규리 | 컴퓨터공학 | 백엔드 리드 & 시스템 아키텍처 | 데이터베이스 물리 설계(ERD 작성) 및 SQL 최적화, DB 논리 모델 정의, 백엔드 주요 API 로직 구현 및 시스템 구조 설계 | [@sophie-24](https://github.com/sophie-24) |
| 김이준 | 컴퓨터공학 | 프론트엔드 개발 & API 연동 | 클라이언트 UI 개발, 백엔드 API 데이터 연동, 구글 OAuth 2.0 로그인 구현, 영상 자막 전처리 모듈 개발 | [@yijuuuun](https://github.com/yijuuuun) |
| 조민선 | 경영정보학 | 팀장 & 서비스 기획 | 프로젝트 일정 관리 및 커뮤니케이션, 데이터 스키마 리서치 및 SQL 초안 작성, 프롬프트 엔지니어링 지원 | [@chomincho](https://github.com/chomincho) |
| 최유민 | 데이터사이언스 | UI/UX 디자인 | 서비스 와이어프레임 설계, 사용자 경험(UX) 중심의 인터페이스 디자인(Figma), 프론트엔드 디자인 가이드 제공 | [@yumin-53](https://github.com/yumin-53) |

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| Backend | FastAPI, Python, APScheduler |
| Database | PostgreSQL (asyncpg/SQLAlchemy) |
| AI | Google Gemini 2.5 Flash Lite (`google.genai`) |
| 인증 | Google OAuth 2.0 + PKCE + JWT |
| 크롬 익스텐션 | Manifest V3 |
| 이메일 발송 | Resend API |
| 자막 수집 | youtube-transcript-api (yt-dlp fallback) |

---

## 서비스 구조

두 개의 독립 파이프라인으로 구성된다.

```
Pipeline A — 라이브 서치 (실시간)
유튜브 검색 / 영상 시청 중 → 크롬 익스텐션 사이드패널 → GET /analyze_search
→ intent_ai ∥ selector_ai (asyncio.gather 병렬)
→ analyzer_ai (영상당 Gemini 1회 병렬 + 교차분석 1회)
→ 사이드패널 렌더링 (신뢰도·광고 여부·요약 카드)

Pipeline B — 뉴스레터 (배치)
사용자가 하트(♥)한 관심 토픽 → 사용자 설정 시간 APScheduler 배치
→ 토픽별 순차: intent_ai ∥ selector_ai (병렬) → analyzer_ai
→ newsletter_ai (조립, Gemini 호출 없음)
→ mailer.py → Resend 이메일 발송 (토픽별 구독 취소 링크 포함)
```

> Pipeline B는 사용자가 직접 하트한 관심 토픽(UserInterest.is_active=True)만 기반으로 동작합니다.
> 관심 토픽이 0개인 유저는 해당 배치에서 skip됩니다.

---

## 실행 방법

### 1. 저장소 클론

```bash
git clone https://github.com/sophie-24/SWproject-Team2-m.git
cd SWproject-Team2
```

### 2. 가상환경 설정

```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 환경변수 설정

`Projects/src/backend/.env` 파일 생성 (팀 톡방에서 값 받기):

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
REDIRECT_URI=http://localhost:8000/auth/callback
YOUTUBE_API_KEY=
GEMINI_API_KEY=
JWT_SECRET=
DATABASE_URL=postgresql+asyncpg://postgres:비밀번호@localhost:5432/techvisibility
FRONTEND_URL=http://localhost:8000
RESEND_API_KEY=
RESEND_FROM_EMAIL=curator@tubify.com
ADMIN_SECRET=
EXTENSION_ID=
```

> JWT_SECRET 생성: `python -c "import secrets; print(secrets.token_hex(32))"`
> `.env`는 절대 커밋하지 말 것 (gitignore 처리됨)

### 4. DB 생성

```bash
psql -U postgres
CREATE DATABASE tubify;
\q
```

> 테이블은 서버 시작 시 자동 생성됨

### 5. 서버 실행

```bash
cd Projects/src/backend
uvicorn main:app --reload --port 8000
```

- 서버: `http://localhost:8000`
- API 문서: `http://localhost:8000/docs`

> 프론트엔드도 동일 주소에서 서빙됨. Live Server 불필요.

포트 충돌 시:
```
netstat -ano | findstr :8000
taskkill /PID [뜬 숫자] /F
```

### 6. 크롬 익스텐션 로드

1. `chrome://extensions` 접속
2. 개발자 모드 ON
3. 압축 해제된 확장 프로그램 로드 → `Projects/src/extension` 선택
4. 익스텐션 ID 확인 → `.env`의 `EXTENSION_ID`에 입력

### 7. cookies.txt 설정

자막 수집 fallback(yt-dlp)을 위해 `backend/` 폴더에 `cookies.txt` 파일 필요 → 팀 톡방에서 받기 (깃에 올리면 안 됨)

---

## 멀티에이전트 역할 분담

| 에이전트 | 파일 | 역할 | Gemini 호출 |
|---------|------|------|------------|
| Intent AI | `intent_ai.py` | 토픽 목록 → 유희형/지식형/구매형 의도 분류 + FORMAT_MAP 반환 | 토픽당 1회 |
| Selector AI | `selector_ai.py` | YouTube API 후보 15개 수집 → ViewRate × 개인화 공식으로 상위 5개 선정 | 없음 (YouTube API) |
| Analyzer AI | `analyzer_ai.py` | 자막 수집 → 영상별 병렬 분석(광고점수·요약·핵심주장) + 교차분석(공통사실·쟁점·장단점) | 영상당 1회 + 교차분석 1회 |
| Newsletter AI | `newsletter_ai.py` | 분석 결과를 의도 타입별 포맷으로 조립 → 최종 뉴스레터 dict | 없음 (순수 조립) |
| Title Topic AI | `title_topic_ai.py` | 영상 제목 → normalized_topic 추출 (플로팅 버튼 단일 영상 분석용) | 1회 (실패 시 regex fallback) |
| Pipeline A Orchestrator | `pipeA_orchestrator.py` | 실시간 검색 흐름 총괄: intent_ai ∥ selector_ai → analyzer_ai | - |
| Pipeline B Orchestrator | `pipeB_orchestrator.py` | 뉴스레터 배치 흐름 총괄: 토픽별 순차 반복, 캐시 히트 시 selector 생략 | - |

**Gemini 호출 수 (Pipeline B, 토픽 3개 기준):**
- intent_ai: 3회
- analyzer_ai 단일 분석: 최대 15회 (토픽당 영상 5개)
- analyzer_ai 교차분석: 3회
- **합계: 최대 21회** (캐시 히트 토픽은 최대 6회 절약)

---

## 사용자 서비스 플로우

```
[최초 접속]
index.html
→ Google 로그인 (OAuth 2.0 PKCE)
→ 신규 유저: onboarding.html → 발송 시간 설정
→ 기존 유저: index.html → home.html로 이동해 관심 토픽 편집 가능

[실시간 분석 — Pipeline A]
유튜브에서 검색 or 영상 시청 중
→ content.js가 키워드/영상 제목 감지 → 플로팅 버튼 표시
→ 버튼 클릭 → 사이드패널 열림
→ GET /analyze_search?keyword=... 호출
  → 캐시 히트: 즉시 결과 반환 (⚡ 배너 표시)
  → 캐시 미스: intent_ai ∥ selector_ai → analyzer_ai
→ 사이드패널에 영상 카드 + 신뢰도 + 광고 여부 + 요약 표시

[뉴스레터 수신 — Pipeline B]
APScheduler가 매분 실행 → 사용자 send_time 비교
→ UserInterest.is_active=True 토픽 조회
→ 토픽이 0개이면 skip
→ 토픽별: intent_ai ∥ selector_ai → analyzer_ai → newsletter_ai 조립
→ Resend로 HTML 이메일 발송
→ 메일 내 각 토픽 카드 하단 "이 주제 구독 취소" 링크
  → GET /interests/unsubscribe-confirm?topic=...
  → mypage.html 리다이렉트 → 확인 후 DELETE /interests/{topic}

[관심 토픽 관리]
dashboard.html → 관심사 편집 → home.html에서 토픽 추가/제거
→ 토픽이 하트된 상태면 다음 배치에서 뉴스레터 대상이 됨
```

---

## 폴더 구조

```
SWproject-Team2/Projects/src/
├── backend/
│   │
│   ├── 🔧 서버 / 인프라
│   ├── main.py                   # FastAPI 앱 진입점 — 모든 HTTP 엔드포인트
│   ├── auth.py                   # Google OAuth2 PKCE 인증 흐름 + JWT 발급/검증
│   ├── database.py               # SQLAlchemy ORM 모델 (User, UserInterest, Newsletter 등)
│   ├── scheduler.py              # APScheduler — 하트 관심 토픽 기반 Pipeline B 배치 실행
│   ├── shared_cache.py           # Pipeline A/B 공유 인메모리 분석 캐시 싱글턴
│   ├── logger.py                 # 앱 전체 공통 로거 — get_logger(name) 헬퍼
│   │
│   ├── 🎬 YouTube / 외부 API
│   ├── transcript_service.py     # YouTube 자막 수집 — youtube-transcript-api 1순위, yt-dlp fallback
│   ├── preprocessing.py          # 자막 텍스트 전처리
│   ├── youtube_search.py         # YouTube Data API — 영상 검색·메타데이터 조회 (싱글톤 클라이언트)
│   ├── gemini_client.py          # Gemini API 비동기 래퍼 — call_gemini_async, Retry/Backoff
│   ├── ad_detector.py            # 광고/협찬 탐지 — 규칙(Layer 1-3) + Gemini 의미론적 탐지(Layer 4)
│   │
│   ├── 📧 발송
│   ├── mailer.py                 # Resend API HTML 뉴스레터 발송 — 의도별 카드 레이아웃 + 토픽별 구독취소 링크
│   │
│   └── 🤖 agents/                # 멀티에이전트 AI 파이프라인
│       ├── pipeA_orchestrator.py # Pipeline A 총괄 — 실시간 검색 분석 (intent∥selector → analyzer)
│       ├── pipeB_orchestrator.py # Pipeline B 총괄 — 하트 토픽 기반 뉴스레터 (토픽별 순차, 내부 병렬)
│       ├── intent_ai.py          # 검색 의도 분류 (유희형/지식형/구매형) + FORMAT_MAP
│       ├── selector_ai.py        # YouTube 영상 선정 — 후보 15개 → ViewRate×개인화 공식 → 상위 5개
│       ├── analyzer_ai.py        # 자막 병렬 분석 — 영상당 Gemini 1회 + 교차분석 1회, Lost in the Middle 방지
│       ├── newsletter_ai.py      # 의도 타입별 뉴스레터 조립 (Gemini 호출 없음)
│       └── title_topic_ai.py     # 영상 제목 → normalized_topic 추출 (Gemini 1회, regex fallback)
│
├── extension/                    # Chrome 익스텐션 (Manifest V3)
│   ├── manifest.json             # 익스텐션 설정 및 권한 선언 (history 권한 없음)
│   ├── config.js                 # API_BASE URL 단일 선언 (환경별 변경점)
│   ├── background.js             # 서비스 워커 — JWT 저장·전달, OAuth fallback 자동 감지
│   ├── content.js                # 유튜브 페이지 키워드/영상 감지 + 플로팅 버튼 (디바운싱 적용)
│   ├── popup.html / popup.js     # 익스텐션 팝업 UI
│   └── side_panel.html           # 사이드패널 — 실시간 검색 분석 결과 (Pipeline A)
│
└── frontend/                     # 웹 프론트엔드 (백엔드와 동일 서버 port 8000에서 서빙)
    ├── index.html                # 메인·로그인 페이지
    ├── loading.html              # OAuth 콜백 후 로딩 페이지 (분석 진행 표시)
    ├── home.html / home.js       # 관심 토픽 편집 페이지
    ├── onboarding.html           # 신규 유저 온보딩 — 뉴스레터 발송 시간 설정
    ├── dashboard.html            # 마이페이지 — 프로필·통계·관심사·뉴스레터 이력
    ├── mypage.html               # 토픽 구독 취소 확인 팝업 (unsubscribe_topic 파라미터)
    ├── search_dashboard.html     # 검색 분석 결과 상세 페이지
    └── admin.html                # 관리자 페이지
```

---

## 브랜치 전략

- `main`: 배포 가능한 안정 버전
- `develop`: 통합 개발 브랜치
- `feature/*`: 기능 개발
- `bugfix/*`: 버그 수정
- `refactor/*`: 리팩토링

## 커밋 컨벤션

```
feat:     새로운 기능 추가
fix:      버그 수정
refactor: 코드 리팩토링
docs:     문서 수정
chore:    빌드/설정 변경
```
