# TechVisibility

> 유튜브 알고리즘 대신, 오늘 내가 관심 가진 주제를 AI가 분석해 뉴스레터로 보내주는 서비스

---

## 목차
- [소개](#소개)
- [팀원](#팀원)
- [기술 스택](#기술-스택)
- [주요 기능](#주요-기능)
- [서비스 플로우](#서비스-플로우)
- [실행 방법](#실행-방법)
- [폴더 구조](#폴더-구조)
- [브랜치 전략](#브랜치-전략)
- [커밋 컨벤션](#커밋-컨벤션)

---

## 소개

유튜브 알고리즘은 내가 보고 싶은 걸 주는 게 아니라 계속 보게 만듭니다.
TechVisibility는 사용자가 오늘 관심 가진 주제를 정리해서, 광고를 걸러내고,
핵심만 뉴스레터(카톡/이메일)로 보내줍니다.

**프로젝트 기간:** `2025.XX.XX - 2025.XX.XX`

---

## 팀원

| 이름 | 역할 | GitHub |
|------|------|--------|
| 이름1 | 역할 | [@id](https://github.com/id) |
| 이름2 | 역할 | [@id](https://github.com/id) |

---

## 기술 스택

- **Frontend:** HTML, CSS, JavaScript
- **Backend:** FastAPI, Python
- **Database:** PostgreSQL, SQLAlchemy (asyncpg)
- **AI:** Google Gemini 2.5 Flash Lite (google-generativeai)
- **크롬 익스텐션:** Manifest V3
- **인증:** Google OAuth 2.0 + PKCE + JWT
- **스케줄러:** APScheduler
- **기타 도구:** yt-dlp (자막 수집), YouTube Data API v3

---

## 주요 기능

- **행동 수집** — 크롬 익스텐션이 유튜브 검색/시청 기록을 실시간 수집
- **주제 클러스터링** — AI가 오늘 수집된 키워드를 의미 단위로 그룹핑
- **영상 선정** — View Rate 기반으로 주제별 상위 5개 영상 선정
- **자막 분석** — yt-dlp로 자막 수집 후 AI가 핵심 내용 추출 (5개 병렬 처리)
- **광고 탐지** — AI가 협찬/광고 포함 영상 자동 감지 및 필터링
- **뉴스레터 생성** — 주제별 요약 + 장단점 + 출처 링크 포함
- **자동 발송** — 매일 저녁 9시 카카오톡 또는 이메일로 발송

---

## 서비스 플로우

```
1. 웹사이트 접속 → 구글 로그인
   → 카톡/이메일 선택 → 개인정보 동의
         ↓
2. 크롬 익스텐션 설치
   → 유튜브에서 검색/시청 시 백엔드로 실시간 전송
         ↓
3. 백엔드가 수집 (같은 주제 2회 이상 검색/시청 시 트리거)
         ↓
4. 저녁 9시 배치 실행
   → 멀티 에이전트 파이프라인 실행
   → cluster_ai → selector_ai → analyzer_ai → newsletter_ai
         ↓
5. 뉴스레터 DB 저장 → 카톡/이메일로 발송
   → 각 내용마다 출처 영상 링크 포함
```

---

## 실행 방법

```bash
git clone https://github.com/yijuuuun/SWproject-Team2.git
cd SWproject-Team2
```

### 가상환경 설치

```bash
python -m venv venv
.\venv\Scripts\activate

pip install -r requirements.txt
```

### 환경변수 설정

```
GOOGLE_CLIENT_ID=발급받은_클라이언트_ID
GOOGLE_CLIENT_SECRET=발급받은_클라이언트_시크릿
REDIRECT_URI=http://localhost:8000/auth/callback
YOUTUBE_API_KEY=발급받은_유튜브_API_키
GEMINI_API_KEY=발급받은_Gemini_API_키
JWT_SECRET=랜덤_문자열
DATABASE_URL=postgresql+asyncpg://postgres:비밀번호@localhost:5432/techvisibility
FRONTEND_URL=http://localhost:8000
EMAIL_SENDER=your@gmail.com
EMAIL_PASSWORD=구글_앱_비밀번호
```

> JWT_SECRET 생성: `python -c "import secrets; print(secrets.token_hex(32))"`
> `.env` 파일은 gitignore 처리 — 절대 커밋하지 말 것

### PostgreSQL DB 생성

```bash
psql -U postgres
CREATE DATABASE techvisibility;
\q
```

> 테이블은 서버 시작 시 자동 생성됨

### 서버 실행

```bash
cd Projects/src/backend
uvicorn main:app --reload --port 8000
```

서버 주소: `http://localhost:8000`
API 문서: `http://localhost:8000/docs`

> 프론트엔드도 `http://localhost:8000`에서 같이 서빙됨. Live Server 불필요.

### 크롬 익스텐션 로드

```
chrome://extensions/ → 개발자 모드 ON
→ 압축해제된 확장 프로그램 로드
→ Projects/src/extension/ 폴더 선택
→ 익스텐션 ID 확인 → extension/background.js의 EXTENSION_ID에 입력
```

---

## 폴더 구조

```
SWproject-Team2/Projects/src/
├── backend/
│   ├── main.py                   # FastAPI 서버 (lifespan 패턴)
│   ├── auth.py                   # Google OAuth + PKCE + JWT
│   ├── database.py               # DB 연결 + 모델
│   ├── scheduler.py              # 배치 스케줄러 (저녁 9시)
│   ├── preprocessing.py          # 자막 전처리 (수정 금지)
│   ├── transcript_service.py     # 자막 수집 (yt-dlp)
│   ├── youtube_search.py         # 유튜브 검색
│   ├── youtube_service.py        # 구독 채널 목록
│   │
│   ├── collector/
│   │   ├── behavior_store.py     # 행동 로그 저장
│   │   └── trigger.py            # 주제 트리거 판단
│   │
│   ├── agents/
│   │   ├── gemini_client.py      # Gemini 공통 클라이언트 ★
│   │   ├── cluster_ai.py         # [AI 1] 주제 클러스터링
│   │   ├── selector_ai.py        # [AI 2] 영상 선정
│   │   ├── analyzer_ai.py        # [AI 3] 자막 분석 + 광고 탐지
│   │   ├── newsletter_ai.py      # [AI 4] 뉴스레터 생성
│   │   └── orchestrator.py       # 파이프라인 총괄
│   │
│   └── delivery/
│       └── email.py              # 이메일 발송
│
├── extension/
│   ├── manifest.json
│   ├── background.js
│   ├── content.js
│   ├── popup.html
│   └── popup.js
│
└── frontend/
    ├── index.html
    ├── onboarding.html
    └── dashboard.html
```

---

## 브랜치 전략

- `main`: 배포 가능한 안정 버전
- `develop`: 통합 개발 브랜치
- `feature/*`: 기능 개발
- `bugfix/*`: 버그 수정

---

## 커밋 컨벤션

```
feat: 새로운 기능 추가
fix: 버그 수정
refactor: 코드 리팩토링
style: 스타일 변경
docs: 문서 수정
chore: 빌드/설정 변경
```
