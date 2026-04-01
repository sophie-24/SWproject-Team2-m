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
```

> `.env` 파일은 톡으로 받은거 설정해서 gitignore 처리하고 커밋하지말기.

### 3. 서버 실행

```bash
uvicorn main:app
```

서버 주소: `http://localhost:8000`

> 프론트엔드도 `http://localhost:8000` 에서 같이 서빙됨. Live Server 불필요.

---

## API 엔드포인트

### 인증

| 메서드 | 경로             | 설명                                       |
| ------ | ---------------- | ------------------------------------------ |
| GET    | `/auth/login`    | 구글 OAuth 로그인 시작 (브라우저에서 접속) |
| GET    | `/auth/callback` | 로그인 완료 후 자동 호출됨                 |

### 데이터

| 메서드 | 경로                                   | 설명                                            |
| ------ | -------------------------------------- | ----------------------------------------------- |
| GET    | `/subscriptions`                       | 로그인 유저의 유튜브 구독 채널 목록             |
| GET    | `/search?keyword=파이썬&max_results=5` | 키워드로 영상 검색                              |
| GET    | `/transcript/{video_id}`               | 영상 자막 + timestamp                           |
| GET    | `/preprocess/{video_id}`               | 자막 수집 → 정제 → 청크 분할 (민선/규리 연동용) |

### `/preprocess` 응답 예시 (민선님/규리님 참고)

```json
{
  "video_id": "abc123",
  "total_chunks": 41,
  "chunks": [
    {
      "text": "오늘은 파이썬에 대해 알아보겠습니다...",
      "metadata": {
        "video_id": "abc123",
        "channel_id": "UC...",
        "timestamp": 12.5,
        "quality_score": 0.82
      }
    }
  ]
}
```

---

## 파일 구조

```
backend/
├── main.py              # FastAPI 서버, 엔드포인트 전부 여기
├── auth.py              # Google OAuth 설정
├── youtube_service.py   # 구독 채널 목록
├── youtube_search.py    # 키워드 영상 검색
├── transcript_service.py# 자막 수집 (yt-dlp)
├── preprocessing.py     # 자막 정제 + 청크 분할
├── orchestrator.py      # 파이프라인. LLM 2~3번 호출, 조건 분기 1개
├── baseline.py          # 단일 LLM (빠름, 판단 없음)
├── evaluator.py         # 실험 준비
└── requirements.txt

frontend/
└── index.html           # 테스트용 UI
```

---

## 주의사항

- 자막 수집을 위해 `cookies.txt` 파일이 `backend/` 폴더 안에 있어야 함 → 톡으로 직접 받은 거 넣기! (깃에 올리면 안 됨)
- 서버 재시작하면 로그인 세션 초기화됨 (다시 로그인 필요)
