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
EMAIL_SENDER=your@gmail.com
EMAIL_PASSWORD=구글_앱_비밀번호
KAKAO_ACCESS_TOKEN=카카오_액세스_토큰
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

> `.env` 파일은 톡으로 받은거 설정해서 gitignore 처리하고 커밋하지말기.

### 3. 서버 실행

```bash
uvicorn main:app --reload --port 8000
```

서버 주소: `http://localhost:8000`
API 문서: `http://localhost:8000/docs`
> 프론트엔드도 `http://localhost:8000` 에서 같이 서빙됨. Live Server 불필요.

### 4. 크롬 익스텐션 로드

1. Chrome 주소창에 `chrome://extensions` 입력
2. 우측 상단 **개발자 모드** 활성화
3. **압축 해제된 확장 프로그램 로드** 클릭
4. `Projects/src/extension` 폴더 선택
5. 익스텐션 ID 확인 → `extension/background.js`의 EXTENSION_ID에 입력

---

## AI 파이프라인
사용자의 오늘 행동 로그를 기반으로 저녁 9시에 자동 실행됩니다.
[수집] 익스텐션 → /collect → behavior_logs DB 저장
↓
[트리거] 같은 주제 2회 이상 → trigger.py 판단
↓
[AI 1] cluster_ai.py    키워드 의미 단위로 클러스터링
↓
[AI 2] selector_ai.py   주제별 영상 후보 선정 (View Rate 기반 상위 5개)
↓
[AI 3] analyzer_ai.py   자막 분석 + 광고 탐지 + 공통 사실/쟁점 추출
↓
[AI 4] newsletter_ai.py 뉴스레터 생성 (요약 + 장단점 + 출처)
↓
[발송] 카카오 친구톡 / 이메일

**Gemini API 호출 수 (주제 1개 기준): 최대 7회**
> 무료 티어 하루 20회 제한 → 테스트 최소화
---

## API 엔드포인트

### 헬스체크

| 메서드 | 경로      | 설명             |
| ------ | --------- | ---------------- |
| GET    | `/health` | 서버 상태 확인   |

### 인증

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/auth/login` | 구글 OAuth 로그인 시작 |
| GET | `/auth/callback` | 로그인 완료 후 JWT 발급 |
| GET | `/auth/me` | 현재 로그인 사용자 확인 |


### 행동 수집 (익스텐션 → 백엔드)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/collect` | 검색/시청 이벤트 수집 (JWT 필요) |
| GET | `/collect/today` | 오늘 수집된 로그 + 트리거 주제 확인 (JWT 필요) |

**`/collect` 요청 예시**
```json
{
  "event_type": "search",
  "keyword": "지성 피부 세럼",
  "video_id": null
}
```
### 구독 설정

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/subscribe` | 수신 방법 설정 (kakao/email) |
| GET | `/subscriptions` | 유튜브 구독 채널 목록 |

### 뉴스레터

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/newsletter/history` | 내 뉴스레터 히스토리 (JWT 필요) |
| POST | `/newsletter/send-now` | 즉시 발송 테스트 (JWT 필요) |

### 데이터

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/search?keyword=파이썬` | 키워드로 영상 검색 |
| GET | `/transcript/{video_id}` | 영상 자막 + timestamp |
| GET | `/preprocess/{video_id}` | 자막 수집 → 정제 → 청크 분할 |

### 관리자 (ADMIN_SECRET 필요)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/admin/users` | 전체 유저 목록 |
| GET | `/admin/logs` | 오늘 전체 행동 로그 |
| POST | `/admin/pipeline/run` | 특정 유저 파이프라인 즉시 실행 |

---

## DB 테이블

| 테이블 | 설명 |
|--------|------|
| `users` | 유저 정보 (google_id, email, delivery_type) |
| `behavior_logs` | 익스텐션 수집 로그 (검색어, 시청 기록) |
| `newsletters` | 발송된 뉴스레터 히스토리 |

**DB 직접 확인 (pgAdmin 권장):**
```sql
SELECT * FROM users;
SELECT * FROM behavior_logs ORDER BY logged_at DESC LIMIT 10;
SELECT * FROM newsletters ORDER BY delivered_at DESC LIMIT 10;
```

---

## 파일 구조

```
backend/
├── main.py                   # FastAPI 서버, 모든 엔드포인트
├── auth.py                   # Google OAuth + JWT 발급/검증
├── database.py               # DB 연결 + 테이블 모델
├── scheduler.py              # 배치 스케줄러 (매일 21:00 KST)
├── preprocessing.py          # 자막 전처리
├── transcript_service.py     # 자막 수집 (yt-dlp)
├── youtube_search.py         # 키워드 영상 검색
├── youtube_service.py        # 구독 채널 목록
│
├── collector/
│   ├── behavior_store.py     # 행동 로그 저장 + 조회
│   └── trigger.py            # 2회 이상 주제 트리거 판단
│
├── agents/
│   ├── cluster_ai.py         # [AI 1] 주제 클러스터링
│   ├── selector_ai.py        # [AI 2] View Rate 기반 영상 선정
│   ├── analyzer_ai.py        # [AI 3] 자막 분석 + 광고 탐지
│   ├── newsletter_ai.py      # [AI 4] 뉴스레터 생성
│   └── orchestrator.py       # 4개 AI 파이프라인 총괄
│
└── delivery/
    ├── kakao.py              # 카카오 친구톡 발송
    └── email.py              # 이메일 발송 (Gmail SMTP)
```

---

## 주의사항

- 자막 수집을 위해 `cookies.txt` 파일이 `backend/` 폴더 안에 있어야 함 → 톡으로 직접 받은 거 넣기! (깃에 올리면 안 됨)
- 서버 재시작하면 로그인 세션 초기화됨 (다시 로그인 필요)
- Gemini 무료 티어 하루 20회 제한 → 테스트 최소화 (검색 1회당 최대 8회 소모)
- `google.genai` 패키지 사용 금지 → `google.generativeai` 사용
- ChromaDB, RAG 방식 사용 금지
