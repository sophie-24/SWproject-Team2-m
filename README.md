# Tubify

> 멀티에이전트 기반 실시간 유튜브 정보 분석 및 메일링 서비스

유튜브 알고리즘은 내가 보고 싶은 걸 주는 게 아니라 계속 보게 만든다.
Tubify는 사용자가 오늘 관심 가진 주제를 AI가 분석해 광고를 걸러내고, 핵심만 뉴스레터로 보내준다.

---

## 팀원

| 이름 | 전공 | 역할 | GitHub |
|------|------|------|--------|
| 김규리 | 컴퓨터공학 | 백엔드 팀장 | [@id](https://github.com/sophie-24) |
| 김이준 | 컴퓨터공학 | 프론트엔드 팀장 & 백엔드 보조 | [@id](https://github.com/yijuuuun) |
| 조민선 | 경영정보학 | 기획 & 팀장 | [@id](https://github.com/id) |
| 최유민 | 데이터사이언스 | 기획 & UI/UX 디자인 | [@id](https://github.com/id) |

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| Backend | FastAPI, Python, APScheduler |
| Database | PostgreSQL (asyncpg/SQLAlchemy), Redis |
| AI | Google Gemini 2.5 Flash Lite (`google.genai`) |
| 인증 | Google OAuth 2.0 + PKCE + JWT |
| 크롬 익스텐션 | Manifest V3 |
| 이메일 발송 | Resend API |
| 자막 수집 | yt-dlp, youtube-transcript-api |

---

## 서비스 구조

두 개의 독립 파이프라인으로 구성된다.

```
Pipeline A — 라이브 서치 (실시간)
유튜브 검색 → 익스텐션 팝업/버튼 → /analyze_search → selector_ai + analyzer_ai → Side Panel 렌더링

Pipeline B — 뉴스레터 (배치)
익스텐션 행동 수집 → behavior_logs → 사용자 설정 시간 배치
→ cluster_ai → selector_ai → analyzer_ai → newsletter_ai → Resend 이메일 발송
```

---

## 실행 방법

### 1. 저장소 클론

```bash
git clone https://github.com/yijuuuun/SWproject-Team2.git
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
```

> JWT_SECRET 생성: `python -c "import secrets; print(secrets.token_hex(32))"`
> `.env`는 절대 커밋하지 말 것 (gitignore 처리됨)

### 4. DB 생성

```bash
psql -U postgres
CREATE DATABASE techvisibility;
\q
```

> 테이블은 서버 시작 시 자동 생성됨
> 단, 기존 테이블에 컬럼 추가 시 아래 SQL을 pgAdmin에서 직접 실행:

```sql
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS initial_intent      VARCHAR(20),
  ADD COLUMN IF NOT EXISTS interest_categories TEXT,
  ADD COLUMN IF NOT EXISTS send_time           VARCHAR(5) DEFAULT '21:00';
```

### 5. 서버 실행

```bash
cd Projects/src/backend
uvicorn main:app --reload --port 8000
```

- 서버: `http://localhost:8000`
- API 문서: `http://localhost:8000/docs`

> 프론트엔드도 동일 주소에서 서빙됨. Live Server 불필요.

### 6. 크롬 익스텐션 로드

1. `chrome://extensions` 접속
2. 개발자 모드 ON
3. 압축 해제된 확장 프로그램 로드 → `Projects/src/extension` 선택
4. 익스텐션 ID 확인 → `extension/background.js`의 `EXTENSION_ID`에 입력

### 7. cookies.txt 설정

자막 수집을 위해 `backend/` 폴더에 `cookies.txt` 파일 필요 → 팀 톡방에서 받기 (깃에 올리면 안 됨)

---

## 폴더 구조

```
SWproject-Team2/Projects/src/
├── backend/
│   ├── main.py                   # FastAPI 서버
│   ├── auth.py                   # Google OAuth + PKCE + JWT
│   ├── database.py               # DB 연결 + 모델
│   ├── scheduler.py              # 배치 스케줄러
│   ├── preprocessing.py          # 자막 전처리 (수정 금지 ⚠️)
│   ├── transcript_service.py     # 자막 수집 (yt-dlp)
│   ├── youtube_search.py         # 유튜브 검색
│   ├── youtube_service.py        # 구독 채널 목록
│   ├── collector/
│   │   ├── behavior_store.py     # 행동 로그 저장
│   │   └── trigger.py            # 주제 트리거 판단
│   ├── agents/
│   │   ├── gemini_client.py      # Gemini 공통 클라이언트 ★
│   │   ├── intent_ai.py          # 검색 의도 분류
│   │   ├── format_ai.py          # 뉴스레터 포맷 결정
│   │   ├── cluster_ai.py         # [AI 1] 주제 클러스터링
│   │   ├── selector_ai.py        # [AI 2] 영상 선정
│   │   ├── analyzer_ai.py        # [AI 3] 자막 분석 + 광고 탐지
│   │   ├── newsletter_ai.py      # [AI 4] 뉴스레터 생성
│   │   └── orchestrator.py       # 파이프라인 총괄
│   └── delivery/
│       └── email.py              # 이메일 발송 (Resend)
├── extension/
│   ├── manifest.json
│   ├── background.js
│   ├── content.js
│   ├── popup.html / popup.js
│   └── side_panel.html
└── frontend/
    ├── index.html
    ├── onboarding.html
    ├── dashboard.html
    ├── search_dashboard.html
    └── admin.html
```

---

## 브랜치 전략

- `main`: 배포 가능한 안정 버전
- `develop`: 통합 개발 브랜치
- `feature/*`: 기능 개발
- `bugfix/*`: 버그 수정

## 커밋 컨벤션

```
feat:     새로운 기능 추가
fix:      버그 수정
refactor: 코드 리팩토링
docs:     문서 수정
chore:    빌드/설정 변경
```
