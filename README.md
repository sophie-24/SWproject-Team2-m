# Tubify

> 멀티에이전트 기반 실시간 유튜브 정보 분석 및 메일링 서비스

유튜브 알고리즘은 내가 보고 싶은 걸 주는 게 아니라 계속 보게 만든다.
Tubify는 사용자가 오늘 관심 가진 주제를 AI가 분석해 광고를 걸러내고, 핵심만 뉴스레터로 보내준다.

---

## 팀원

| 이름 | 전공 | 역할 | GitHub |
|------|------|------|--------|
<<<<<<< Updated upstream
| 김규리 | 컴퓨터공학 | 백엔드 / AI 파이프라인 | [@id](https://github.com/id) |
| 김이준 | 컴퓨터공학 | 백엔드 / DB | [@id](https://github.com/id) |
| 조민선 | 경영정보학 | 프론트엔드 | [@id](https://github.com/id) |
| 최유민 | 데이터사이언스 | 크롬 익스텐션 | [@id](https://github.com/id) |
=======
| 김규리 | 컴퓨터공학 | 백엔드 | [@sophie-24](https://github.com/sophie-24) |
| 김이준 | 컴퓨터공학 | 프론트엔드 & 백엔드 (영상 자막 전처리, 구글 로그인) | [@yijuuuun](https://github.com/yijuuuun) |
| 조민선 | 경영정보학 | 팀장 & DB 설계 | [@chomincho](https://github.com/chomincho) |
| 최유민 | 데이터사이언스 |  UI/UX 디자인 | [@yumin-53](https://github.com/yumin-53) |
>>>>>>> Stashed changes

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

만약에 엑세스 권한에 의해 숨겨진 소켓에 액세스를 시도했다는 문구가 뜬다면
```
netstat -ano | findstr :8000
taskkill /PID [뜬 숫자] /F
```
### 6. 크롬 익스텐션 로드

1. `chrome://extensions` 접속
2. 개발자 모드 ON
3. 압축 해제된 확장 프로그램 로드 → `Projects/src/extension` 선택
4. 익스텐션 ID 확인 → `extension/background.js`의 `EXTENSION_ID`에 입력

### 7. cookies.txt 설정

자막 수집을 위해 `backend/` 폴더에 `cookies.txt` 파일 필요 → 팀 톡방에서 받기 (깃에 올리면 안 됨)

---
## 서비스 구조
멀티에이전트 역할 분담

- Intent AI : 유희/지식/구매 의도 분류 및 뉴스레터 톤앤매너 결정
- Cluster AI : 시간 흐름과 의미적 유사성을 기반으로 주제 그룹화
- Selector AI : 조회수 대비 시청률 + 개인화 가중치로 상위 5개 선정
- Analyzer AI : 자막 전처리 후 교차 분석을 통한 신뢰도 점수 산출
- Newletter AI : 위 모든 결과를 이메일 레이아웃에 맞춰 최종 조립

---

## 폴더 구조

```
SWproject-Team2/Projects/src/
├── backend/
│   │
│   ├── 🔧 서버 / 인프라
│   ├── main.py                   # FastAPI 앱 진입점 — 모든 HTTP 엔드포인트 (인증·분석·뉴스레터·자막·대시보드)
│   ├── auth.py                   # Google OAuth2 PKCE 인증 흐름 + JWT 발급/검증
│   ├── database.py               # SQLAlchemy ORM 모델 및 비동기 DB 연결 (User, BehaviorLog, Newsletter 등)
│   ├── scheduler.py              # APScheduler 기반 Pipeline B 배치 실행 — 사용자별 send_time에 뉴스레터 생성·발송
│   ├── shared_cache.py           # Pipeline A/B 공유 인메모리 분석 캐시 (search_analysis_cache 싱글턴)
│   ├── logger.py                 # 앱 전체 공통 로거 설정 — get_logger(name) 헬퍼
│   │
│   ├── 📥 데이터 수집
│   ├── behavior_store.py         # 사용자 행동 로그 DB 저장·조회 (search/watch 이벤트, Pipeline B 원천 데이터)
│   ├── trigger.py                # 행동 로그 기반 뉴스레터 주제 트리거 판단 (시간 감쇠·연속 시청 가중치)
│   ├── transcript_service.py     # yt-dlp로 YouTube 자막 수집, 타임스탬프 포맷 변환 (수정 주의 ⚠️)
│   ├── preprocessing.py          # 자막 텍스트 전처리 — 노이즈 제거(이모지·반복어), 청킹 (수정 주의 ⚠️)
│   │
│   ├── 🎬 YouTube / 외부 API
│   ├── youtube_search.py         # YouTube Data API — 영상 검색·메타데이터 조회, 단일 영상 fetch, 구독 채널 목록
│   ├── gemini_client.py          # Gemini API 비동기 래퍼 — call_gemini_async, parse_section, parse_bullet_list
│   ├── ad_detector.py            # 광고/협찬 탐지 — description·자막 규칙(Layer 1-2) + API 플래그(Layer 3)
│   │
│   ├── 📧 발송
│   ├── mailer.py                 # Resend API HTML 뉴스레터 이메일 발송 — 의도별 카드 레이아웃(썸네일·쟁점배지)
│   │
│   └── 🤖 agents/                # 멀티에이전트 AI 파이프라인 (Pipeline B)
│       ├── orchestrator.py       # Pipeline B 총괄 — intent→cluster→select→analyze→newsletter 순차 실행
│       ├── intent_ai.py          # 검색 의도 분류 (유희형/지식형/구매형) + 포맷 스타일(길이·톤·구조) 결정
│       ├── cluster_ai.py         # 오늘 검색어를 시간 흐름 컨텍스트 포함해 의미 기반 주제 클러스터링
│       ├── selector_ai.py        # YouTube 후보 수집 후 ViewRate × 개인화(키워드·구독·최신성) 공식으로 상위 5개 선정
│       ├── analyzer_ai.py        # 자막 배치 분석 — 광고 탐지, 교차분석(공통사실·쟁점), 신뢰도 점수
│       └── newsletter_ai.py      # analyzer 결과를 의도 타입별로 조립해 최종 뉴스레터 데이터 반환
│
├── extension/                    # Chrome 익스텐션
│   ├── manifest.json             # 익스텐션 설정 및 권한 선언
│   ├── background.js             # 서비스 워커 — JWT 저장, 웹사이트↔익스텐션 토큰 전달
│   ├── content.js                # 유튜브 페이지 행동 수집 (search/watch 이벤트 → /collect 전송)
│   ├── popup.html / popup.js     # 익스텐션 팝업 UI
│   └── side_panel.html           # 사이드패널 — 실시간 검색 분석 결과 렌더링 (Pipeline A)
│
└── frontend/                     # 웹 프론트엔드
    ├── index.html                # 메인 페이지
    ├── onboarding.html           # 온보딩 — 관심사·의도·발송 시간 설정
    ├── dashboard.html            # 마이페이지 대시보드 — 프로필·통계·관심사
    ├── search_dashboard.html     # 검색 분석 결과 상세 페이지
    └── admin.html                # 관리자 페이지
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
