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
```

> `.env` 파일은 톡으로 받은거 설정해서 gitignore 처리하고 커밋하지말기.

### 3. 서버 실행

```bash
uvicorn main:app --reload --port 8000
```

서버 주소: `http://localhost:8000`

> 프론트엔드도 `http://localhost:8000` 에서 같이 서빙됨. Live Server 불필요.

### 4. 크롬 익스텐션 로드

1. Chrome 주소창에 `chrome://extensions` 입력
2. 우측 상단 **개발자 모드** 활성화
3. **압축 해제된 확장 프로그램 로드** 클릭
4. `Projects/src/extension` 폴더 선택

---

## AI 파이프라인

검색어 입력 시 4단계 AI가 순차/병렬 실행됩니다.

```
[AI 1] selector_ai.py   영상 후보 10개 수집 → 쇼츠 제거 → 점수 계산 → 상위 5개 선정
         ↓                    ↘
[AI 2] analyzer_ai.py        [AI 3] category_ai.py   (병렬 실행)
  5개 영상 동시 분석               검색 의도 분류
  자막 수집, 광고 탐지              정보탐색형 / 비교구매형 / 학습튜토리얼형
  공통 사실 / 쟁점 추출
         ↓                    ↙
[AI 4] dashboard_ai.py  핵심 요약 3줄 + 공통 결론 + 추천 영상 순위 생성
```

**Gemini API 호출 수 (검색 1회 기준): 최대 8회**

---

## API 엔드포인트

### 헬스체크

| 메서드 | 경로      | 설명             |
| ------ | --------- | ---------------- |
| GET    | `/health` | 서버 상태 확인   |

### 인증

| 메서드 | 경로             | 설명                                       |
| ------ | ---------------- | ------------------------------------------ |
| GET    | `/auth/login`    | 구글 OAuth 로그인 시작 (브라우저에서 접속) |
| GET    | `/auth/callback` | 로그인 완료 후 자동 호출됨                 |

### AI 분석 (메인)

| 메서드 | 경로              | 설명                              |
| ------ | ----------------- | --------------------------------- |
| POST   | `/analyze_search` | 4단계 AI 파이프라인 실행, 대시보드 반환 |

**`/analyze_search` 요청 예시**

```json
{
  "keyword": "파이썬 입문",
  "subscribed_channel_ids": ["UCxxxx", "UCyyyy"]
}
```

**`/analyze_search` 응답 예시**

```json
{
  "keyword": "파이썬 입문",
  "category": "학습튜토리얼형",
  "layout": { "layout": "step_guide", "primary_section": "common_facts", ... },
  "summary_lines": ["파이썬은 ...", "초보자에게 ...", "주요 라이브러리로 ..."],
  "common_conclusion": "파이썬은 진입 장벽이 낮고 ...",
  "common_facts": ["문법이 간결하다", "라이브러리가 풍부하다"],
  "controversies": ["IDE 선택 기준에 대해 의견이 갈림"],
  "recommended_videos": [
    {
      "video_id": "abc123",
      "title": "파이썬 입문 강의",
      "final_score": 0.82,
      "is_subscribed": false,
      "ad_detected": false,
      ...
    }
  ]
}
```

### 데이터

| 메서드 | 경로                                   | 설명                              |
| ------ | -------------------------------------- | --------------------------------- |
| GET    | `/subscriptions`                       | 로그인 유저의 유튜브 구독 채널 목록 |
| GET    | `/search?keyword=파이썬&max_results=5` | 키워드로 영상 검색                 |
| GET    | `/transcript/{video_id}`               | 영상 자막 + timestamp             |
| GET    | `/preprocess/{video_id}`               | 자막 수집 → 정제 → 청크 분할      |

---

## 파일 구조

```
backend/
├── main.py               # FastAPI 서버, 모든 엔드포인트
├── orchestrator.py       # 4개 AI 연결 파이프라인
├── selector_ai.py        # [AI 1] 영상 후보 선정
├── analyzer_ai.py        # [AI 2] 5개 영상 동시 분석
├── category_ai.py        # [AI 3] 검색 의도 분류
├── dashboard_ai.py       # [AI 4] 대시보드 생성
├── auth.py               # Google OAuth 설정
├── youtube_service.py    # 구독 채널 목록
├── youtube_search.py     # 키워드 영상 검색
├── transcript_service.py # 자막 수집 (yt-dlp)
├── preprocessing.py      # 자막 정제 + 청크 분할 (수정 금지)
└── requirements.txt

extension/
├── manifest.json         # 크롬 익스텐션 설정 (manifest v3)
├── content.js            # 유튜브 검색어 감지 + 오버레이 삽입
├── popup.html            # 팝업 UI
└── popup.js              # OAuth 로그인 + 구독 채널 수집

frontend/
└── index.html            # 테스트용 웹 UI
```

---

## 주의사항

- 자막 수집을 위해 `cookies.txt` 파일이 `backend/` 폴더 안에 있어야 함 → 톡으로 직접 받은 거 넣기! (깃에 올리면 안 됨)
- 서버 재시작하면 로그인 세션 초기화됨 (다시 로그인 필요)
- Gemini 무료 티어 하루 20회 제한 → 테스트 최소화 (검색 1회당 최대 8회 소모)
- `preprocessing.py` 수정 금지 (팀원 코드)
