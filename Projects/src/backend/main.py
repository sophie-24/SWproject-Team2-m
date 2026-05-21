import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Depends, BackgroundTasks, Cookie
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Optional
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from auth import create_auth_url, exchange_code_for_tokens, create_jwt, verify_jwt
from youtube_search import search_videos, get_subscriptions
from transcript_service import get_transcript, format_transcript_with_timestamps, list_available_transcripts
from preprocessing import chunk_transcript
from gemini_client import call_gemini_async
from shared_cache import search_analysis_cache as _search_analysis_cache_shared
from database import init_db, get_db, Newsletter, UserInterest, UserInterestVideo
from agents.pipeB_orchestrator import run_pipeline
from scheduler import start_scheduler, stop_scheduler

load_dotenv()
from logger import get_logger
logger = get_logger(__name__)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "../frontend")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "admin1234")
EXTENSION_ID = os.getenv("EXTENSION_ID", "")
# HTML 내 "__EXTENSION_ID__" 플레이스홀더 치환용 — 따옴표 없이 raw ID만 삽입
# (HTML 템플릿에서 const EXTENSION_ID = "__EXTENSION_ID__" 형태로 이미 따옴표로 감싸져 있음)
_ext_ids = [x.strip() for x in EXTENSION_ID.split(",") if x.strip()]
EXTENSION_IDS_JS = _ext_ids[0] if _ext_ids else ""
EXTENSION_STORE_URL = os.getenv("EXTENSION_STORE_URL", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행 (on_event 대체)"""
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Tubify API",
    version="1.0.0",
    description="""
사용자가 직접 하트(♥)한 관심 토픽을 AI가 분석해 개인화 뉴스레터를 발송하는 서비스입니다.

---

## 🔐 JWT 인증 방법

**1단계 — 로그인 & 토큰 복사**
1. [`/auth/login`](/auth/login) 접속 → Google 로그인
2. 리다이렉트된 URL의 `?token=` 이후 값 전체 복사

**2단계 — Swagger에서 인증**
1. 이 페이지 우측 상단 **Authorize 🔓** 버튼 클릭
2. `Bearer <복사한_토큰>` 입력 (앞에 `Bearer ` 포함) → Authorize

이후 모든 API를 **Try it out → Execute** 로 바로 테스트할 수 있습니다.

> JWT가 필요한 엔드포인트는 summary에 🔑 표시가 있습니다.

---

## 📋 주요 플로우

### 하트 관심 토픽 추가
```
POST /analyze_video  { "video_id": "dQw4w9WgXcQ", "title": "영상 제목" }
  → title_topic_ai가 토픽 추출
  → POST /interests  { "title": "영상 제목", "video_id": "..." }
  → 최대 5개 제한
```

### 뉴스레터 즉시 발송 테스트
```
POST /newsletter/send-now
  → 내 하트 관심 토픽 기반으로 뉴스레터 생성 후 이메일 발송
  → 관심 토픽이 0개이면 발송 안 됨
```

### 발송 시간 변경
```
PATCH /settings/send_time  { "send_time": "08:00" }
  → 다음 배치부터 해당 시간에 발송
```

---

## 🏷 아이콘 범례
- ✅ 테스트 완료
- 🚧 미테스트 / 개발 중
- ⚠️ DEPRECATED — 뉴스레터 발송에 사용 안 함 (Issue 8 제거 예정)
""",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "인증",        "description": "Google OAuth 로그인 및 JWT 발급. `/auth/login`으로 시작 → 리다이렉트 URL의 `?token=` 값을 Authorize에 입력하세요."},
        {"name": "프로필",      "description": "내 프로필 조회·수정. `GET /my/profile`은 하트 관심 토픽 목록도 함께 반환합니다."},
        # DEPRECATED (Issue 9): 온보딩 태그 제거
        {"name": "구독 설정",   "description": "뉴스레터 수신 동의·거부 및 발송 시간 변경. `PATCH /settings/send_time`으로 단일 HH:MM 문자열 전송."},
        {"name": "관심사",      "description": "하트(♥) 기반 관심 토픽 관리. 최대 5개. `POST /interests`로 추가, `DELETE /interests/{topic}`으로 취소(soft delete)."},
        {"name": "AI 분석",     "description": "Pipeline A — 실시간 검색 분석(사이드패널). `GET /analyze_search?keyword=검색어`로 즉시 테스트 가능."},
        {"name": "뉴스레터",    "description": "뉴스레터 히스토리 조회 및 즉시 발송 테스트. `POST /newsletter/send-now`로 관심 토픽 기반 발송 테스트."},
        {"name": "YouTube",     "description": "YouTube 구독 채널 목록 조회 및 영상 검색."},
        {"name": "자막",        "description": "YouTube 영상 자막 원문 조회 및 가용 언어 확인."},
        {"name": "전처리",      "description": "자막 청크 변환 — analyzer_ai에 넣기 전 전처리 결과 확인용."},
        {"name": "행동 수집",   "description": "⚠️ DEPRECATED — 익스텐션 검색·시청 이벤트 수집. 뉴스레터 발송에 더 이상 사용 안 함."},
        {"name": "프론트엔드",  "description": "정적 HTML, CSS, JS 파일 제공 (Swagger 테스트 불필요)."},
        {"name": "상태 확인",   "description": "서버 헬스체크. 인증 없이 `GET /health`로 바로 확인 가능."},
        {"name": "관리자",      "description": "관리자 전용. 요청 헤더에 `Admin-Secret: <값>` 필요. `POST /admin/pipeline/run?user_id=xxx`로 특정 유저 즉시 발송 테스트."},
    ],
)
security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://www.youtube.com",  # content.js가 유튜브 페이지 컨텍스트에서 /collect 호출
        os.getenv("FRONTEND_URL", ""),  # Cloudtype 배포 URL
        "chrome-extension://" + os.getenv("EXTENSION_ID", ""),  # 크롬 익스텐션
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 전역 예외 핸들러 — 500 plain text → JSON 변환 (디버깅용) ───────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception(f"[500] {request.method} {request.url.path} — {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )

# 정적 파일 서빙 (frontend/ 폴더)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# OAuth 진행 중인 요청별 PKCE 데이터 (state → code_verifier)
# Redis 도입 전 임시 구현 — 단일 워커 환경에서만 안전
_oauth_sessions: dict[str, str] = {}  # {state: code_verifier}
_oauth_credentials: dict[str, dict] = {}  # {state: credentials}
_oauth_ext_states: set = set()          # 익스텐션 팝업 로그인 state 집합

_transcript_cache: dict = {}
# Pipeline A 분석 캐시 — shared_cache 모듈과 동일 객체 참조
# Pipeline B(scheduler)도 이 캐시를 읽어 Gemini 중복 호출 방지
_search_analysis_cache = _search_analysis_cache_shared
_search_analysis_lock = asyncio.Lock()   # 동일 키워드 동시 요청 시 중복 Gemini 호출 방지


# ── JWT 인증 의존성 ────────────────────────────────────────────────────────────

def get_current_user(
    token=Depends(optional_security),
    access_token: Optional[str] = Cookie(None),
):
    token_value = token.credentials if token else access_token
    if token_value and token_value.startswith("Bearer "):
        token_value = token_value.removeprefix("Bearer ").strip()

    user = verify_jwt(token_value) if token_value else None
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


class GenericObjectResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class HealthResponse(BaseModel):
    status: str


class AuthMeResponse(BaseModel):
    user_id: str
    email: str


class SuccessResponse(BaseModel):
    success: bool


class OkResponse(BaseModel):
    ok: bool


class MessageResponse(SuccessResponse):
    message: str


class BehaviorLogItem(BaseModel):
    event_type: str
    keyword: str
    video_id: Optional[str] = None
    logged_at: str


class CollectResponse(BaseModel):
    saved: bool
    count: int


class TodayLogsResponse(BaseModel):
    total_logs: int
    logs: list[BehaviorLogItem]
    triggered_topics: list[str]


class MyLogsResponse(BaseModel):
    total: int
    logs: list[BehaviorLogItem]
    triggered_topics: list[str]
    profile_categories: list[str]
    merged_topics: list[str]


class SendTimeResponse(SuccessResponse):
    send_time: str          # 단일 HH:MM 문자열


class SettingsResponse(BaseModel):
    send_time: str          # 단일 HH:MM 문자열
    is_subscribed: bool
    delivery_type: Optional[str] = None
    email: Optional[str] = None


class InterestTopicItem(BaseModel):
    """GET /my/profile 응답에 포함되는 하트 관심 토픽 요약."""
    topic: str
    normalized_topic: Optional[str] = None


class ProfileResponse(BaseModel):
    email: Optional[str] = None
    send_time: str                          # 단일 HH:MM 문자열 (Issue 7)
    initial_intent: Optional[str] = None
    interest_categories: list[str]
    interests: list[InterestTopicItem]      # 하트 관심 토픽 목록 (Issue 7)
    is_subscribed: bool
    created_at: Optional[str] = None


class StatsResponse(BaseModel):
    today_log_count: int
    triggered_topics: list[str]
    total_newsletters: int
    last_sent_at: Optional[str] = None


class InterestItem(BaseModel):
    category: str
    weight: float
    updated_at: Optional[str] = None


class InterestsResponse(BaseModel):
    interests: list[InterestItem]


# DEPRECATED (Issue 9): HistoryAnalyzeResponse 제거 — /profile/analyze-history 엔드포인트 제거

class SubscriptionsResponse(BaseModel):
    count: int
    subscriptions: list[dict[str, Any]]


class SearchResponse(BaseModel):
    count: int
    videos: list[dict[str, Any]]


class NewsletterItem(BaseModel):
    id: str
    subject: str
    content_json: Optional[str] = None
    delivered_at: str
    delivery_status: Optional[str] = None


class NewsletterHistoryResponse(BaseModel):
    newsletters: list[NewsletterItem]


class AnalyzeSearchResponse(GenericObjectResponse):
    keyword: Optional[str] = None


class VideoAnalyzeResponse(BaseModel):
    video_id: str
    ad_score: float
    summary: str
    key_claims: list[Any]
    credibility_score: float
    ad_detected: bool


class TranscriptAvailableResponse(BaseModel):
    video_id: str
    available: list[Any]


class TranscriptResponse(BaseModel):
    video_id: str
    count: int
    transcript: list[Any]


class PreprocessResponse(BaseModel):
    video_id: str
    total_chunks: int
    chunks: list[Any]


class AdminUserItem(BaseModel):
    id: str
    google_id: str
    email: Optional[str] = None
    delivery_type: Optional[str] = None
    created_at: str


class AdminUsersResponse(BaseModel):
    total: int
    users: list[AdminUserItem]


class AdminBehaviorLogItem(BehaviorLogItem):
    user_id: str


class AdminLogsResponse(BaseModel):
    total: int
    logs: list[AdminBehaviorLogItem]


# ── 정적 파일 ─────────────────────────────────────────────────────────────────

@app.get("/", tags=["프론트엔드"], summary="서비스 소개 페이지 제공 ✅", response_class=FileResponse)
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "intro.html"))

@app.get("/login", tags=["프론트엔드"], summary="로그인 페이지 제공 ✅", response_class=HTMLResponse)
def login_page():
    with open(os.path.join(FRONTEND_DIR, "login.html"), "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__EXTENSION_ID__", EXTENSION_IDS_JS)
    return HTMLResponse(content=html)

@app.get("/extension-guide.html", tags=["프론트엔드"], summary="크롬 익스텐션 설치 안내 페이지 제공 ✅", response_class=HTMLResponse)
def extension_guide():
    with open(os.path.join(FRONTEND_DIR, "extension-guide.html"), "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__EXTENSION_ID__", EXTENSION_IDS_JS)
    html = html.replace("__EXTENSION_STORE_URL__", EXTENSION_STORE_URL)
    return HTMLResponse(content=html)

@app.get("/mypage.html", tags=["프론트엔드"], summary="마이페이지 제공 ✅", response_class=FileResponse)
def mypage():
    return FileResponse(os.path.join(FRONTEND_DIR, "mypage.html"))


@app.get("/privacy.html", tags=["프론트엔드"], summary="개인정보 처리방침 페이지 제공 ✅", response_class=FileResponse)
def privacy():
    return FileResponse(os.path.join(FRONTEND_DIR, "privacy.html"))

@app.get("/terms.html", tags=["프론트엔드"], summary="약관 페이지 제공 ✅", response_class=FileResponse)
def terms():
    return FileResponse(os.path.join(FRONTEND_DIR, "terms.html"))

@app.get("/intro.html", tags=["프론트엔드"], summary="서비스 소개 페이지 제공 ✅", response_class=FileResponse)
def intro():
    return FileResponse(os.path.join(FRONTEND_DIR, "intro.html"))

@app.get("/app.js", tags=["프론트엔드"], summary="공통 앱 스크립트 제공 ✅", response_class=FileResponse)
def serve_app_js():
    return FileResponse(os.path.join(FRONTEND_DIR, "app.js"), media_type="application/javascript")

@app.get("/style.css", tags=["프론트엔드"], summary="공통 스타일시트 제공 ✅", response_class=FileResponse)
def serve_style_css():
    return FileResponse(os.path.join(FRONTEND_DIR, "style.css"), media_type="text/css")


# ── 헬스체크 ──────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["상태 확인"], summary="서버 상태 확인 ✅")
def health():
    return {"status": "ok"}


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/login", tags=["인증"], summary="Google OAuth 로그인 시작 ✅", response_class=RedirectResponse)
def login(ext: bool = False):
    auth_url, state, code_verifier = create_auth_url()
    _oauth_sessions[state] = code_verifier
    if ext:
        _oauth_ext_states.add(state)  # 익스텐션 팝업 로그인으로 표시
    logger.debug(f"[login] state 저장: {state} ext={ext}")
    return RedirectResponse(auth_url)


@app.get("/auth/callback", tags=["인증"], summary="Google OAuth 콜백 처리 ✅", response_class=RedirectResponse)
async def callback(
    code: str,
    state: str,
    db : AsyncSession = Depends(get_db)
):
    logger.debug(f"[callback] state 수신: {state}")

    code_verifier = _oauth_sessions.pop(state, None)  # 사용 후 즉시 제거
    if not code_verifier:
        logger.error(f"[callback] state 없음 (서버 재시작됐거나 중복 요청): {state}")
        raise HTTPException(status_code=400, detail="로그인 세션이 만료됐습니다. 다시 로그인해주세요.")

    # 동기 블로킹 함수(requests.post + id_token 검증)를 스레드풀에서 실행
    # 이벤트 루프 블락 방지
    try:
        user_info = await asyncio.to_thread(exchange_code_for_tokens, code, code_verifier)
    except Exception as e:
        logger.error(f"[callback] 토큰 교환 실패: {e}")
        raise HTTPException(status_code=502, detail=f"Google 인증 실패: {e}")

    import json as _json
    creds_data = user_info.get("credentials")
    _oauth_credentials[state] = creds_data  # 메모리 캐시 유지 (기존 호환)

    from database import User
    from sqlalchemy import select

    result = await db.execute(
        select(User).where(User.google_id == user_info["google_id"])
    )
    user = result.scalar_one_or_none()

    is_new_user = False
    if not user:
        user = User(
            google_id=user_info["google_id"],
            email=user_info["email"],
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        is_new_user = True
        logger.info(f"[callback] 신규 유저 생성: {user_info['email']}")
    else:
        logger.info(f"[callback] 기존 유저 로그인: {user_info['email']}")

    # OAuth credentials DB 저장 — 서버 재시작 후에도 /subscriptions 동작하도록
    if creds_data:
        user.oauth_credentials = _json.dumps(creds_data, ensure_ascii=False)
        await db.commit()

    jwt_token = create_jwt(
        user_id=user_info["google_id"],
        email=user_info["email"],
    )
    # 익스텐션 팝업 로그인 → 자동 닫힘 전용 페이지로 리다이렉트
    is_ext = state in _oauth_ext_states
    _oauth_ext_states.discard(state)  # 사용 후 즉시 제거

    if is_ext:
        redirect_url = f"{FRONTEND_URL}/auth/extension-done?token={jwt_token}"
    else:
        # 신규 유저 → 크롬 익스텐션 설치 안내, 기존 유저 → 마이페이지
        if is_new_user:
            redirect_url = f"{FRONTEND_URL}/extension-guide.html?token={jwt_token}"
        else:
            redirect_url = f"{FRONTEND_URL}/mypage.html?token={jwt_token}"

    response = RedirectResponse(url=redirect_url)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {jwt_token}",
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return response


@app.get("/auth/extension-done", tags=["인증"], summary="익스텐션 팝업 로그인 완료 — 자동 닫힘")
def extension_done(token: str = ""):
    """
    익스텐션 팝업 OAuth 완료 후 리다이렉트되는 페이지.
    - background.js tabs.onUpdated가 ?token= 을 감지해 JWT를 storage에 저장.
    - 페이지 자체는 window.close()로 팝업을 즉시 닫음.
    """
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html lang="ko">
<head><meta charset="utf-8"><title>Tubify 로그인 완료</title></head>
<body>
<p style="font-family:sans-serif;text-align:center;margin-top:60px;color:#555;">
  로그인 완료! 이 창은 자동으로 닫힙니다…
</p>
<script>window.close();</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/auth/me", response_model=AuthMeResponse, tags=["인증"], summary="현재 로그인 사용자 조회 ✅")
def me(user=Depends(get_current_user)):
    return {"user_id": user["user_id"], "email": user["email"]}


# ── 행동 데이터 수집 ───────────────────────────────────────────────────────────

class CollectData(BaseModel):
    event_type: str = Field("search", description="'search' 또는 'watch'")
    keyword: str = Field("FastAPI Swagger 테스트", description="검색어 또는 영상 제목")
    video_id: Optional[str] = Field(None, description="시청 이벤트일 때 YouTube video_id")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_type": "search",
                "keyword": "FastAPI Swagger 테스트",
                "video_id": None,
            }
        }
    )


@app.post(
    "/collect",
    response_model=CollectResponse,
    deprecated=True,
    tags=["행동 수집"],
    summary="검색/시청 로그 저장 ✅",
)
async def collect(
    data: CollectData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    ⚠️ **DEPRECATED** — 행동 로그는 더 이상 뉴스레터 발송에 사용되지 않습니다.

    익스텐션 하위 호환성을 위해 엔드포인트는 유지하되 저장하지 않습니다.
    뉴스레터는 하트(♥) 관심 토픽(`POST /interests`) 기반으로 발송됩니다.
    """
    # DEPRECATED: behavior_store 제거 (Issue 8) — 익스텐션 호환성 유지를 위해 success만 반환
    return {"success": True}

@app.get(
    "/collect/today",
    response_model=TodayLogsResponse,
    deprecated=True,
    tags=["행동 수집"],
    summary="오늘 수집된 행동 로그 조회 ✅",
)
async def today_logs(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    ⚠️ **DEPRECATED** — 행동 로그 기반 파이프라인 제거(Issue 8)로 항상 빈 결과를 반환합니다.

    하트 관심 토픽 확인: `GET /interests`
    """
    # DEPRECATED: behavior_store 제거 (Issue 8)
    return {"total_logs": 0, "logs": [], "triggered_topics": []}


@app.get(
    "/my/logs",
    response_model=MyLogsResponse,
    deprecated=True,
    tags=["행동 수집"],
    summary="내 행동 로그 및 트리거 주제 조회 ✅",
)
async def my_logs(
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    ⚠️ **DEPRECATED** — 행동 로그 기반 파이프라인 제거(Issue 8)로 항상 빈 결과를 반환합니다.

    하트 관심 토픽 확인: `GET /interests`
    """
    # DEPRECATED: BehaviorLog / trigger 제거 (Issue 8)
    return {
        "total":              0,
        "logs":               [],
        "triggered_topics":   [],
        "profile_categories": [],
        "merged_topics":      [],
    }

# ── 발송 시간 유효성 검사 유틸 ────────────────────────────────────────────────

_DEFAULT_SEND_TIME = "21:00"
_DEFAULT_SEND_TIMES = ["08:00", "21:00"]


def _validate_send_time(send_time: str) -> str:
    """
    발송 시간 유효성 검사 후 정규화된 값 반환.

    - 형식: HH:MM (00:00 ~ 23:59)
    - 임의 시간 허용 — scheduler가 매분 체크해 일치하는 유저만 배치 처리

    Raises:
        HTTPException 400: 형식 오류
    """
    import re as _re
    if not _re.match(r"^([01]\d|2[0-3]):[0-5]\d$", send_time):
        raise HTTPException(
            status_code=400,
            detail="send_time은 HH:MM 형식이어야 합니다 (예: '07:30', '21:00')",
        )
    return send_time


def _parse_send_times(raw: Optional[str]) -> list[str]:
    import json as _json

    if not raw:
        return _DEFAULT_SEND_TIMES.copy()
    try:
        parsed = _json.loads(raw)
        if isinstance(parsed, list):
            times = [str(t) for t in parsed if isinstance(t, str) and t.strip()]
        elif isinstance(parsed, str):
            times = [parsed]
        else:
            times = []
    except Exception:
        times = [raw]

    valid_times = []
    for value in times:
        try:
            valid_times.append(_validate_send_time(value))
        except HTTPException:
            continue
    return sorted(set(valid_times)) or _DEFAULT_SEND_TIMES.copy()


def _serialize_send_times(send_time: list[str]) -> str:
    import json as _json

    if not isinstance(send_time, list) or not send_time:
        raise HTTPException(status_code=400, detail="send_time은 ['08:00', '21:00'] 형식이어야 합니다.")
    validated = [_validate_send_time(value) for value in send_time]
    return _json.dumps(sorted(set(validated)), ensure_ascii=False)


async def _get_or_create_user(db: AsyncSession, current_user: dict):
    from database import User

    result = await db.execute(select(User).where(User.google_id == current_user["user_id"]))
    db_user = result.scalar_one_or_none()
    if db_user:
        return db_user

    db_user = User(
        google_id=current_user["user_id"],
        email=current_user["email"],
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    logger.info(f"[user] JWT 기반 사용자 자동 생성: {current_user['email']}")
    return db_user

# ── 구독 설정 ─────────────────────────────────────────────────────────────────
# DEPRECATED (Issue 9): SubscribeData / /subscribe 엔드포인트 제거 — send_time 설정은 PATCH /settings/send_time 사용

# ── 마이페이지: 발송 시간 변경 ────────────────────────────────────────────────

class SendTimeData(BaseModel):
    send_time: str = Field(
        "21:00",
        description="발송 시간 (HH:MM 형식, 예: '08:00', '21:00')",
    )

    model_config = ConfigDict(
        json_schema_extra={"example": {"send_time": "21:00"}}
    )


@app.patch(
    "/settings/send_time",
    response_model=SendTimeResponse,
    tags=["구독 설정"],
    summary="뉴스레터 발송 시간 변경 ✅",
)
@app.patch(
    "/my/send-time",
    response_model=SendTimeResponse,
    tags=["구독 설정"],
    summary="내 뉴스레터 발송 시간 변경 ✅ (별칭 — /settings/send_time과 동일 핸들러)",
)
async def update_send_time(
    data: SendTimeData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    뉴스레터 발송 시간을 변경합니다.

    **요청:**
    ```json
    { "send_time": "08:00" }
    ```

    **응답:**
    ```json
    { "success": true, "send_time": "08:00" }
    ```

    - 허용 형식: `HH:MM` (00:00 ~ 23:59)
    - 변경 즉시 다음 배치부터 반영됩니다.
    - 권장 값: `"08:00"` (아침), `"21:00"` (저녁, 기본값)
    """
    validated = _validate_send_time(data.send_time)
    import json as _json
    serialized = _json.dumps([validated], ensure_ascii=False)  # DB: JSON 배열로 저장 (스케줄러 하위 호환)

    db_user = await _get_or_create_user(db, user)

    prev_time = db_user.send_time
    db_user.send_time = serialized
    await db.commit()

    logger.info(f"[send-time] {user['user_id']} {prev_time} → {serialized}")
    return {"success": True, "send_time": validated}


@app.get(
    "/my/settings",
    response_model=SettingsResponse,
    tags=["구독 설정"],
    summary="내 구독 설정 조회 ✅",
)
async def get_my_settings(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    마이페이지 설정 조회.
    발송 시간, 수신 동의 여부, 배송 방법 반환.
    """
    db_user = await _get_or_create_user(db, user)

    times = _parse_send_times(db_user.send_time)
    return {
        "send_time":      times[0] if times else "21:00",
        "is_subscribed":  db_user.is_subscribed,
        "delivery_type":  db_user.delivery_type,
        "email":          db_user.email,
    }


# ── 프로필 조회 / 수정 / 통계 ─────────────────────────────────────────────────

@app.get(
    "/my/profile",
    response_model=ProfileResponse,
    tags=["프로필"],
    summary="내 프로필 조회 ✅",
)
async def my_profile(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    내 프로필 전체를 반환합니다.

    **응답에 포함되는 내용:**
    - `email`: 뉴스레터 수신 이메일
    - `send_time`: 발송 시간 단일 문자열 (예: `"21:00"`)
    - `initial_intent`: 의도 유형 (`"유희형"` / `"지식형"` / `"구매형"`)
    - `interest_categories`: 온보딩 시 설정한 관심사 카테고리 배열 (레거시)
    - `interests`: **하트(♥) 관심 토픽 목록** — `[{"topic": "...", "normalized_topic": "..."}]`
    - `is_subscribed`: 뉴스레터 수신 동의 여부

    > `interests`가 비어 있으면 뉴스레터가 발송되지 않습니다.
    """
    import json as _json

    db_user = await _get_or_create_user(db, user)

    # interest_categories: 온보딩 시 저장된 JSON 배열
    categories = []
    if db_user.interest_categories:
        try:
            categories = _json.loads(db_user.interest_categories)
        except Exception:
            pass

    # send_time: DB의 JSON 배열에서 첫 번째 값만 반환 (단일 시간)
    times = _parse_send_times(db_user.send_time)
    single_time = times[0] if times else "21:00"

    # interests: user_interests 테이블의 활성 하트 토픽
    interest_rows = await db.execute(
        select(UserInterest)
        .where(
            UserInterest.user_id == user["user_id"],
            UserInterest.is_active == True,  # noqa: E712
        )
        .order_by(UserInterest.created_at.asc())
    )
    interests = [
        {"topic": i.category, "normalized_topic": i.normalized_topic}
        for i in interest_rows.scalars().all()
    ]

    return {
        "email":               db_user.email,
        "send_time":           single_time,
        "initial_intent":      db_user.initial_intent,
        "interest_categories": categories,
        "interests":           interests,
        "is_subscribed":       db_user.is_subscribed,
        "created_at":          db_user.created_at.isoformat() if db_user.created_at else None,
    }

class ProfileUpdateData(BaseModel):
    send_time: Optional[str] = Field(
        None,
        description="발송 시간 (HH:MM 형식, 예: '08:00', '21:00')",
    )
    interest_categories: Optional[list[str]] = Field(
        None,
        description="관심사 카테고리 목록",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "send_time": "21:00",
                "interest_categories": ["AI", "경제", "테크"],
            }
        }
    )


@app.put(
    "/my/profile",
    response_model=OkResponse,
    tags=["프로필"],
    summary="내 프로필 수정 ✅",
)
async def update_my_profile(
    data: ProfileUpdateData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """발송 시간 / 관심사 수정.
    관심사 변경 시 user_interests에 신규 카테고리만 추가 (기존 weight 유지).
    send_time은 단일 HH:MM 문자열로 수용 (DB는 JSON 배열로 저장 — 스케줄러 하위 호환).
    """
    import json as _json
    from datetime import datetime, timezone

    db_user = await _get_or_create_user(db, user)

    if data.send_time is not None:
        validated = _validate_send_time(data.send_time)
        db_user.send_time = _json.dumps([validated], ensure_ascii=False)

    if data.interest_categories is not None:
        import re as _re
        db_user.interest_categories = _json.dumps(data.interest_categories, ensure_ascii=False)
        for category in data.interest_categories:
            normalized = _re.sub(r"\s+", " ", category.lower()).strip()
            stmt = (
                pg_insert(UserInterest)
                .values(
                    user_id=user["user_id"],
                    category=category,
                    normalized_topic=normalized,
                    source="onboarding",
                    weight=1,
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                .on_conflict_do_nothing(constraint="uq_user_interest_normalized")
            )
            await db.execute(stmt)

    await db.commit()
    logger.info(f"[profile/update] {user['user_id']} 프로필 수정 완료")
    return {"ok": True}


@app.get(
    "/my/stats",
    response_model=StatsResponse,
    tags=["프로필"],
    summary="내 활동 통계 조회 ✅",
)
async def my_stats(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """오늘 활동 통계 — 로그 수(DEPRECATED→0), 트리거된 토픽(DEPRECATED→[]), 총 뉴스레터 수, 마지막 발송 시각"""
    # DEPRECATED (Issue 8): BehaviorLog 제거 — 항상 0 반환
    from database import Newsletter

    today_log_count  = 0
    triggered_topics = []

    total_r = await db.execute(
        select(func.count()).select_from(Newsletter).where(
            Newsletter.user_id == user["user_id"]
        )
    )
    total_newsletters = total_r.scalar()

    last_r = await db.execute(
        select(Newsletter.delivered_at)
        .where(Newsletter.user_id == user["user_id"])
        .order_by(Newsletter.delivered_at.desc())
        .limit(1)
    )
    last_sent = last_r.scalar_one_or_none()

    return {
        "today_log_count":   today_log_count,
        "triggered_topics":  triggered_topics,
        "total_newsletters": total_newsletters,
        "last_sent_at":      last_sent.isoformat() if last_sent else None,
    }


@app.get(
    "/my/interests",
    response_model=InterestsResponse,
    tags=["관심사"],
    summary="내 관심사 랭킹 조회 ✅",
)
async def my_interests(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """유저 관심사 목록 — weight 내림차순 상위 20개 반환 (dashboard 차트용)"""
    rows = await db.execute(
        select(UserInterest)
        .where(UserInterest.user_id == user["user_id"])
        .order_by(UserInterest.weight.desc())
        .limit(20)
    )
    interests = rows.scalars().all()
    return {
        "interests": [
            {
                "category":   i.category,
                "weight":     i.weight,
                "updated_at": i.updated_at.isoformat() if i.updated_at else None,
            }
            for i in interests
        ]
    }


# ── 하트 기반 관심 토픽 관리 (/interests) ────────────────────────────────────

INTEREST_LIMIT = 5  # 관심 토픽 최대 개수


class InterestAddRequest(BaseModel):
    video_id: Optional[str] = Field(None, description="하트를 누른 YouTube video_id")
    title:    str  = Field(..., description="하트를 누른 영상 제목")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"video_id": "dQw4w9WgXcQ", "title": "갤럭시 S25 울트라 완벽 분석"}
        }
    )


class InterestAddResponse(BaseModel):
    added:            bool
    deduped:          bool
    topic:            str
    normalized_topic: str
    count:            int
    limit:            int


@app.get(
    "/interests",
    tags=["관심사"],
    summary="🔑 하트 관심 토픽 목록 조회 ✅",
)
async def get_interests(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    사용자의 활성 관심 토픽 목록을 반환합니다.

    **응답 예시:**
    ```json
    {
      "interests": [
        {
          "id": "uuid",
          "topic": "갤럭시 S25",
          "normalized_topic": "갤럭시 s25",
          "video_count": 2,
          "created_at": "2026-05-19T12:00:00"
        }
      ],
      "count": 1,
      "limit": 5
    }
    ```

    - `is_active=False`인 취소된 토픽은 포함되지 않습니다.
    - `video_count`: 해당 토픽에 연결된 하트 영상 수
    """
    rows = await db.execute(
        select(UserInterest)
        .where(
            UserInterest.user_id == user["user_id"],
            UserInterest.is_active == True,
        )
        .order_by(UserInterest.created_at.asc())
    )
    interests = rows.scalars().all()

    result = []
    for i in interests:
        video_count_row = await db.execute(
            select(func.count()).select_from(UserInterestVideo)
            .where(UserInterestVideo.user_interest_id == i.id)
        )
        video_count = video_count_row.scalar() or 0
        result.append({
            "id":               str(i.id),
            "topic":            i.category,
            "normalized_topic": i.normalized_topic,
            "video_count":      video_count,
            "created_at":       i.created_at.isoformat() if i.created_at else None,
        })

    return JSONResponse({"interests": result, "count": len(result), "limit": INTEREST_LIMIT})


@app.post(
    "/interests",
    response_model=InterestAddResponse,
    tags=["관심사"],
    summary="🔑 하트 관심 토픽 추가 ✅",
)
async def add_interest(
    data: InterestAddRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    영상에 하트를 눌렀을 때 호출합니다.

    **처리 순서:**
    1. `title_topic_ai`로 영상 제목 → 관심 토픽명 추출
    2. `normalized_topic` 기준 중복 판단
    3. 중복 토픽이면 영상만 연결 (`deduped: true`, 슬롯 소비 없음)
    4. 신규 토픽이면 5개 제한 확인 후 저장

    **요청 예시:**
    ```json
    { "video_id": "dQw4w9WgXcQ", "title": "갤럭시 S25 울트라 완벽 분석" }
    ```

    **응답 예시 — 신규 추가:**
    ```json
    { "added": true, "deduped": false, "topic": "갤럭시 S25", "normalized_topic": "갤럭시 s25", "count": 2, "limit": 5 }
    ```

    **응답 예시 — 중복 토픽 (영상만 연결):**
    ```json
    { "added": false, "deduped": true, "topic": "갤럭시 S25", "normalized_topic": "갤럭시 s25", "count": 2, "limit": 5 }
    ```

    **409:** 이미 5개 토픽이 있고 신규 토픽을 추가하려 할 때

    # TODO: 하트 관심 토픽 API 연결 (프론트 side_panel.js)
    # TODO: 관심 토픽 최대 5개 안내 후 마이페이지 이동 (409 응답 시 프론트 처리)
    """
    import re as _re
    from agents.title_topic_ai import extract_topic_from_title
    from datetime import datetime, timezone

    user_id = user["user_id"]

    # ── Step 1: 제목에서 토픽 추출 ────────────────────────────────────────────
    topic_result     = await extract_topic_from_title(data.title)
    topic            = topic_result["topic"]
    normalized_topic = topic_result["normalized_topic"]

    # ── Step 2: 기존 관심사 중복 판단 (normalized_topic 기준) ─────────────────
    existing_row = await db.execute(
        select(UserInterest).where(
            UserInterest.user_id         == user_id,
            UserInterest.normalized_topic == normalized_topic,
        )
    )
    existing = existing_row.scalar_one_or_none()

    if existing:
        # 비활성 상태였으면 다시 활성화
        if not existing.is_active:
            existing.is_active = True
            await db.commit()

        # 영상 reference 연결 (중복 video_id는 무시)
        if data.video_id:
            await _link_video(db, existing.id, data.video_id, data.title)

        active_count = await _active_interest_count(db, user_id)
        logger.info(f"[interests] 중복 토픽 — 영상만 연결: user={user_id} topic={topic}")
        return {
            "added":            False,
            "deduped":          True,
            "topic":            existing.category,
            "normalized_topic": existing.normalized_topic,
            "count":            active_count,
            "limit":            INTEREST_LIMIT,
        }

    # ── Step 3: 신규 토픽 — 5개 제한 검사 ────────────────────────────────────
    active_count = await _active_interest_count(db, user_id)
    if active_count >= INTEREST_LIMIT:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"관심 토픽은 최대 {INTEREST_LIMIT}개까지 저장할 수 있습니다.",
                "count":   active_count,
                "limit":   INTEREST_LIMIT,
            },
        )

    # ── Step 4: 신규 관심 토픽 저장 ──────────────────────────────────────────
    new_interest = UserInterest(
        user_id          = user_id,
        category         = topic,
        normalized_topic = normalized_topic,
        source           = "manual",
        weight           = 1,
        is_active        = True,
        last_seen_at     = datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(new_interest)
    await db.flush()   # id 확보

    if data.video_id:
        await _link_video(db, new_interest.id, data.video_id, data.title)
    await db.commit()

    active_count += 1
    logger.info(f"[interests] 신규 토픽 추가: user={user_id} topic={topic} count={active_count}")
    return {
        "added":            True,
        "deduped":          False,
        "topic":            topic,
        "normalized_topic": normalized_topic,
        "count":            active_count,
        "limit":            INTEREST_LIMIT,
    }


@app.delete(
    "/interests/{topic}",
    tags=["관심사"],
    summary="🔑 관심 토픽 취소 ✅",
)
async def delete_interest(
    topic: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    관심 토픽을 취소합니다 (soft delete — `is_active=False`).

    - `{topic}` 파라미터: 취소할 토픽명 (예: `갤럭시 S25`)
    - 대소문자·공백 정규화 후 `normalized_topic` 기준으로 조회합니다.
    - 연결된 영상(`user_interest_videos`)은 삭제되지 않고 유지됩니다.
    - 다시 하트를 누르면 같은 슬롯이 재활성화됩니다.

    **404:** 해당 토픽이 없거나 이미 취소된 경우
    """
    import re as _re
    normalized = _re.sub(r"\s+", " ", topic.lower()).strip()

    row = await db.execute(
        select(UserInterest).where(
            UserInterest.user_id          == user["user_id"],
            UserInterest.normalized_topic == normalized,
            UserInterest.is_active        == True,
        )
    )
    interest = row.scalar_one_or_none()
    if not interest:
        raise HTTPException(status_code=404, detail="해당 관심 토픽을 찾을 수 없습니다.")

    interest.is_active = False
    await db.commit()

    logger.info(f"[interests] 토픽 취소: user={user['user_id']} topic={topic}")
    return JSONResponse({"ok": True, "topic": interest.category, "normalized_topic": normalized})


# ── /interests 헬퍼 ────────────────────────────────────────────────────────────

async def _active_interest_count(db: AsyncSession, user_id: str) -> int:
    """활성 관심 토픽 수 반환."""
    result = await db.execute(
        select(func.count()).select_from(UserInterest).where(
            UserInterest.user_id  == user_id,
            UserInterest.is_active == True,
        )
    )
    return result.scalar() or 0


async def _link_video(
    db: AsyncSession,
    user_interest_id,
    video_id: str,
    title: str,
) -> None:
    """관심 토픽에 영상 연결 — 중복 video_id는 무시."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert_local
    stmt = (
        pg_insert_local(UserInterestVideo)
        .values(
            user_interest_id=user_interest_id,
            video_id=video_id,
            title=title,
        )
        .on_conflict_do_nothing(constraint="uq_interest_video")
    )
    await db.execute(stmt)


@app.get(
    "/interests/unsubscribe-confirm",
    tags=["관심사"],
    summary="메일 내 관심 토픽 취소 확인 진입점 (Issue 5)",
    response_class=RedirectResponse,
)
async def interest_unsubscribe_confirm(
    topic: str = Query(..., description="취소할 관심 토픽"),
):
    """
    뉴스레터 메일의 관심 토픽 취소 링크 클릭 시 진입.
    즉시 삭제하지 않고 마이페이지로 이동시켜 확인 팝업을 띄운다.

    # TODO: 관심 토픽 취소 확인 팝업 표시 (프론트 mypage.html)
    # TODO: 메일 링크 위변조 방지 토큰 검증 추가 (Issue 5)
    """
    redirect_url = f"{FRONTEND_URL}/mypage.html?unsubscribe_topic={topic}"
    return RedirectResponse(url=redirect_url)


# DEPRECATED (Issue 9): /profile/init 엔드포인트 제거 — 온보딩 플로우 제거


# DEPRECATED (Issue 9): /profile/analyze-history 엔드포인트 제거 — 온보딩 플로우 제거


@app.delete(
    "/my/subscription",
    response_model=MessageResponse,
    tags=["구독 설정"],
    summary="뉴스레터 수신 해지 ✅",
)
async def unsubscribe(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    뉴스레터 수신 해지.
    users.is_subscribed = False + unsubscribed_at 기록.
    이후 배치에서 완전히 제외됨.
    """
    from database import User
    from datetime import datetime, timezone

    result = await db.execute(
        select(User).where(User.google_id == user["user_id"])
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    db_user.is_subscribed   = False
    db_user.unsubscribed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    logger.info(f"[unsubscribe] {user['user_id']} 수신 해지 완료")
    return {"success": True, "message": "수신이 해지되었습니다. 언제든 다시 구독할 수 있습니다."}


@app.post(
    "/my/subscription",
    response_model=MessageResponse,
    tags=["구독 설정"],
    summary="뉴스레터 수신 재신청 ✅",
)
async def resubscribe(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    뉴스레터 수신 재신청 (해지 후 복구).
    users.is_subscribed = True + unsubscribed_at 초기화.
    """
    from database import User

    result = await db.execute(
        select(User).where(User.google_id == user["user_id"])
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    db_user.is_subscribed   = True
    db_user.unsubscribed_at = None
    await db.commit()

    logger.info(f"[resubscribe] {user['user_id']} 수신 재신청 완료")
    return {"success": True, "message": "수신 신청이 완료되었습니다."}


@app.delete(
    "/my/withdraw",
    response_model=SuccessResponse,
    tags=["프로필"],
    summary="회원 탈퇴 ✅",
)
async def withdraw(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    회원 탈퇴 — 사용자 계정 및 관련 데이터 삭제.
    users, user_interests(→ user_interest_videos CASCADE), behavior_logs, newsletters 모두 제거.
    """
    from database import User, UserInterest, BehaviorLog, Newsletter
    from sqlalchemy import delete as sql_delete

    user_id = user["user_id"]

    await db.execute(sql_delete(Newsletter).where(Newsletter.user_id == user_id))
    await db.execute(sql_delete(BehaviorLog).where(BehaviorLog.user_id == user_id))
    await db.execute(sql_delete(UserInterest).where(UserInterest.user_id == user_id))
    await db.execute(sql_delete(User).where(User.google_id == user_id))
    await db.commit()

    logger.info(f"[withdraw] {user_id} 회원 탈퇴 완료")
    return {"success": True}


# ── YouTube ───────────────────────────────────────────────────────────────────

@app.get(
    "/subscriptions",
    response_model=SubscriptionsResponse,
    tags=["YouTube"],
    summary="YouTube 구독 목록 조회 ✅",
)
async def subscriptions(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """유튜브 구독 목록 조회 (마이페이지용) + 채널 ID를 DB에 캐싱.
    캐싱된 channel_id 목록은 scheduler에서 selector_ai 가산점에 활용됨.
    OAuth credentials은 로그인 시 DB에 저장되어 서버 재시작 후에도 동작.
    """
    import json as _json
    from database import User

    result = await db.execute(select(User).where(User.google_id == user["user_id"]))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    # ── OAuth credentials 로드: 메모리 캐시 → DB 순으로 탐색 ──────────────────
    creds_data = next(iter(_oauth_credentials.values()), None) if _oauth_credentials else None
    if not creds_data and db_user.oauth_credentials:
        try:
            creds_data = _json.loads(db_user.oauth_credentials)
        except Exception:
            creds_data = None

    if not creds_data:
        raise HTTPException(
            status_code=401,
            detail="구글 재로그인이 필요합니다 (OAuth credentials 없음)",
        )

    creds = Credentials(
        token=creds_data["token"],
        refresh_token=creds_data.get("refresh_token"),
        token_uri=creds_data["token_uri"],
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=creds_data["scopes"],
    )
    subs = get_subscriptions(creds)

    # ── 구독 채널 ID DB 캐싱 — scheduler selector_ai 가산점용 ───────────────────
    channel_ids = [s["channel_id"] for s in subs if s.get("channel_id")]
    if channel_ids:
        db_user.subscribed_channels = _json.dumps(channel_ids, ensure_ascii=False)
        await db.commit()
        logger.info(f"[subscriptions] {user['user_id']} 채널 {len(channel_ids)}개 캐싱")

    return JSONResponse({"count": len(subs), "subscriptions": subs})


@app.get(
    "/search",
    response_model=SearchResponse,
    tags=["YouTube"],
    summary="YouTube 영상 검색 ✅",
)
def search(
    keyword: str = Query(...),
    max_results: int = Query(10, ge=1, le=50),
):
    results = search_videos(keyword, max_results)
    return JSONResponse({"count": len(results), "videos": results})


# ── 뉴스레터 ──────────────────────────────────────────────────────────────────

@app.get(
    "/newsletter/history",
    response_model=NewsletterHistoryResponse,
    tags=["뉴스레터"],
    summary="🔑 뉴스레터 히스토리 조회 ✅",
)
async def newsletter_history(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    내 뉴스레터 발송 히스토리를 반환합니다 (최근 20개).

    **응답 주요 필드:**
    - `delivery_status`: `"sent"` / `"failed"` / `"generated"`
    - `content_json`: newsletter_ai 전체 출력 JSON (토픽·요약·출처 포함)
    """
    result = await db.execute(
        select(Newsletter)
        .where(Newsletter.user_id == user["user_id"])
        .order_by(Newsletter.delivered_at.desc())
        .limit(20)
    )
    newsletters = result.scalars().all()

    return JSONResponse({
        "newsletters": [
            {
                "id":              str(n.id),
                "subject":         n.subject,
                "content_json":    n.content_json,
                "delivered_at":    n.delivered_at.isoformat(),
                "delivery_status": n.delivery_status,
            }
            for n in newsletters
        ]
    })


@app.post(
    "/newsletter/send-now",
    tags=["뉴스레터"],
    summary="🔑 즉시 발송 테스트 ✅",
)
async def send_now(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    스케줄러를 기다리지 않고 즉시 뉴스레터를 생성·발송합니다. **테스트용으로 자주 사용하세요.**

    **발송 토픽:** 하트 관심 토픽 (`user_interests.is_active=True`, 최신 순)

    **400:** 하트한 관심 토픽이 없을 때 — 마이페이지에서 관심사를 먼저 추가하세요

    **주의:** Gemini API를 실제로 호출하므로 무료 티어 한도 소모됩니다.
    """
    import json as _json
    from database import Newsletter as NewsletterModel, UserInterest

    user_id = user["user_id"]

    # 하트 관심 토픽 (is_active=True, 최신 순) — 유일한 발송 기준
    interest_result = await db.execute(
        select(UserInterest.category)
        .where(
            UserInterest.user_id == user_id,
            UserInterest.is_active == True,
        )
        .order_by(UserInterest.created_at.desc())
        .limit(10)
    )
    topics = [row[0] for row in interest_result.all()]

    if not topics:
        raise HTTPException(
            status_code=400,
            detail="하트한 관심 토픽 없음 — 마이페이지에서 관심사를 먼저 추가하세요",
        )

    newsletter = await run_pipeline(
        user_id=user_id,
        raw_keywords=topics,
        skip_clustering=True,  # 하트 토픽은 이미 정제됨
    )

    record = NewsletterModel(
        user_id=user_id,
        subject=newsletter.get("subject", ""),
        content_json=_json.dumps(newsletter, ensure_ascii=False),
        delivery_status="generated",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # 이메일 발송
    from mailer import send_email as _send_email
    from database import User
    user_result = await db.execute(select(User).where(User.google_id == user_id))
    db_user = user_result.scalar_one_or_none()
    email_result = _send_email(
        user_email=db_user.email if db_user else "",
        newsletter=newsletter,
        newsletter_type="interest",
    )

    record.delivery_status = "sent" if email_result.get("success") else "failed"
    await db.commit()

    # Issue 8: _update_user_interests DEPRECATED 제거 — weight 누적 없음

    return JSONResponse({
        **newsletter,
        "email_sent": email_result.get("success", False),
        "sent_to": db_user.email if db_user else "",
    })


# ── 즉석 검색 분석 ────────────────────────────────────────────────────────────

@app.get(
    "/analyze_search",
    response_model=AnalyzeSearchResponse,
    tags=["AI 분석"],
    summary="🔑 검색어 즉석 분석 (Pipeline A) ✅",
)
async def analyze_search(
    keyword: str = Query(..., min_length=1),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    검색어에 대한 YouTube 영상 분석 결과를 즉시 반환합니다 (Pipeline A).

    **Swagger 테스트 방법:**
    - `keyword` 파라미터에 검색어 입력 (예: `갤럭시 S25`, `파이썬 강의`)
    - Execute 클릭 → 영상 분석, 공통사실, 쟁점, 추천 영상 목록 반환

    **캐시 동작:**
    - 동일 `{user_id}:{keyword}` 조합은 캐시에서 즉시 반환 (Gemini 재호출 없음)
    - 캐시 히트 시 응답에 `"cached": true` 포함

    **소요 시간:** 최초 분석 10~30초 / 캐시 히트 즉시
    """
    from pipeA_orchestrator import run_pipeline_a
    from database import User

    user_id = user["user_id"]
    cache_key = f"{user_id}:{keyword}"

    if cache_key in _search_analysis_cache:
        return JSONResponse(_search_analysis_cache[cache_key])

    async with _search_analysis_lock:
        if cache_key in _search_analysis_cache:
            return JSONResponse(_search_analysis_cache[cache_key])

        interest_result = await db.execute(
            select(UserInterest.category)
            .where(UserInterest.user_id == user_id)
            .order_by(UserInterest.weight.desc())
            .limit(10)
        )
        user_categories = [row[0] for row in interest_result.all()]

        # ── 구독 채널 ID 조회 (/subscriptions 호출 시 캐싱된 값) ──────────────
        user_row = await db.execute(select(User).where(User.google_id == user_id))
        db_user  = user_row.scalar_one_or_none()
        subscribed_channel_ids = []
        if db_user and db_user.subscribed_channels:
            try:
                subscribed_channel_ids = _json.loads(db_user.subscribed_channels)
            except Exception:
                subscribed_channel_ids = []
        clicked_channel_ids = []

        try:
            result = await run_pipeline_a(
                keyword=keyword,
                subscribed_channel_ids=subscribed_channel_ids,
                user_categories=user_categories,
                clicked_channel_ids=clicked_channel_ids,
            )
        except ValueError:
            result = {"keyword": keyword, "videos": [], "common_facts": [], "controversies": []}

        _search_analysis_cache[cache_key] = result

    return JSONResponse(result)


# ── 영상 진입 분석 (단일 영상 풀 분석 + 키워드 분석 병렬) ────────────────────────

class AnalyzeVideoRequest(BaseModel):
    video_id: str = Field(..., description="현재 보고 있는 YouTube video_id")
    title: str    = Field(..., description="현재 영상 제목")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "video_id": "dQw4w9WgXcQ",
                "title":    "갤럭시 S25 울트라 완벽 분석 리뷰",
            }
        }
    )


class SingleVideoTab(BaseModel):
    """Tab 1 — 현재 시청 중인 영상 단독 분석."""
    video_id:          str
    title:             str
    channel_title:     str
    thumbnail_url:     str
    url:               str
    summary:           str
    key_claims:        list[str]
    ad_score:          int
    ad_detected:       bool
    credibility_score: float


class KeywordAnalysisTab(BaseModel):
    """Tab 2 — 키워드 기반 상위 5개 영상 통합 분석 (Pipeline A 결과)."""
    keyword:            str
    category:           str
    layout:             str
    intent_type:        str
    summary_lines:      list[str]
    common_facts:       list[str]
    controversies:      list[str]
    recommended_videos: list[Any]
    pros:               list[Any]
    cons:               list[Any]


class VideoSourceItem(BaseModel):
    """Tab 3 소스 아이템 — 단일 영상 + 키워드 영상 통합, video_id 기준 중복 제거."""
    video_id:         str
    title:            str
    url:              str
    channel_title:    str
    thumbnail_url:    str
    ad_detected:      bool
    is_current_video: bool   # 현재 시청 중인 영상이면 True


class AnalyzeVideoResponse(BaseModel):
    video_id:          str
    extracted_topic:   str
    normalized_topic:  str
    single_video:      SingleVideoTab
    keyword_analysis:  KeywordAnalysisTab
    sources:           list[VideoSourceItem]


@app.post(
    "/analyze_video",
    response_model=AnalyzeVideoResponse,
    tags=["AI 분석"],
    summary="🔑 영상 진입 분석 — 현재 영상 요약 + 제목 기반 인사이트 ✅",
)
async def analyze_video(
    data: AnalyzeVideoRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    사용자가 YouTube 영상 진입 시 호출합니다.

    **사이드패널 3탭 구조 반환:**
    - `single_video` (Tab 1): 현재 영상 단독 풀 분석 (요약·핵심주장·광고점수·신뢰도)
    - `keyword_analysis` (Tab 2): 제목 추출 토픽 기반 상위 5개 영상 통합 분석
    - `sources` (Tab 3): 두 분석에 사용된 영상 소스 통합, video_id 기준 중복 제거

    **처리 순서:**
    1. 영상 제목 → `title_topic_ai`로 대표 토픽 추출
    2. 단일 영상 풀 분석 + Pipeline A를 asyncio.gather로 병렬 실행
    3. 소스 중복 제거 (단일 영상이 상위 5개에 포함되면 최대 5개 소스 유지)
    """
    from pipeA_orchestrator import run_pipeline_a
    from agents.title_topic_ai import extract_topic_from_title
    from database import User

    video_id = data.video_id
    title    = data.title
    user_id  = user["user_id"]

    # ── Step 1: 제목 기반 토픽 추출 ──────────────────────────────────────────
    topic_result     = await extract_topic_from_title(title)
    extracted_topic  = topic_result["topic"]
    normalized_topic = topic_result["normalized_topic"]
    logger.info(f"[analyze_video] topic='{extracted_topic}' video_id={video_id}")

    # ── Step 2: 유저 관심사 + 구독 채널 조회 (Pipeline A 개인화용) ───────────
    interest_result = await db.execute(
        select(UserInterest.category)
        .where(UserInterest.user_id == user_id)
        .order_by(UserInterest.weight.desc())
        .limit(10)
    )
    user_categories = [row[0] for row in interest_result.all()]

    user_row = await db.execute(select(User).where(User.google_id == user_id))
    db_user  = user_row.scalar_one_or_none()
    subscribed_channel_ids = []
    if db_user and db_user.subscribed_channels:
        try:
            subscribed_channel_ids = _json.loads(db_user.subscribed_channels)
        except Exception:
            subscribed_channel_ids = []
    clicked_channel_ids = []
    if db_user and db_user.watched_channels:
        try:
            clicked_channel_ids = _json.loads(db_user.watched_channels)
        except Exception:
            clicked_channel_ids = []

    # ── Step 3: 단일 영상 풀 분석 + Pipeline A 병렬 실행 ─────────────────────
    single_cache_key   = f"single_video_full:{video_id}"
    pipeline_cache_key = f"{user_id}:video:{normalized_topic}"

    async def _run_single():
        if single_cache_key in _search_analysis_cache:
            return _search_analysis_cache[single_cache_key]
        result = await _full_analyze_single_video(video_id, title, extracted_topic)
        _search_analysis_cache[single_cache_key] = result
        return result

    async def _run_pipeline():
        if pipeline_cache_key in _search_analysis_cache:
            return _search_analysis_cache[pipeline_cache_key]
        try:
            result = await run_pipeline_a(
                keyword=extracted_topic,
                subscribed_channel_ids=subscribed_channel_ids,
                user_categories=user_categories,
                clicked_channel_ids=clicked_channel_ids,
            )
        except ValueError:
            result = {
                "keyword": extracted_topic, "category": "정보탐색형",
                "layout": "summary_focus", "intent_type": "지식형",
                "summary_lines": [], "common_facts": [], "controversies": [],
                "recommended_videos": [], "pros": [], "cons": [], "sources": [],
            }
        _search_analysis_cache[pipeline_cache_key] = result
        return result

    single_result, pipeline_result = await asyncio.gather(_run_single(), _run_pipeline())

    # ── Step 3.5: 시청 채널 ID 누적 저장 (selector_ai ω₄ click_score용) ───────
    watched_channel_id = single_result.get("channel_id")
    if db_user and watched_channel_id:
        try:
            current = clicked_channel_ids[:]
            if watched_channel_id not in current:
                current.append(watched_channel_id)
            db_user.watched_channels = _json.dumps(current[-50:], ensure_ascii=False)  # 최대 50개 유지
            await db.commit()
        except Exception as e:
            logger.warning(f"[analyze_video] watched_channels 저장 실패: {e}")

    # ── Step 4: 소스 통합 — video_id 기준 중복 제거 ──────────────────────────
    seen_ids: set[str] = set()
    merged_sources = []

    seen_ids.add(video_id)
    merged_sources.append({
        "video_id":         video_id,
        "title":            title,
        "url":              f"https://youtube.com/watch?v={video_id}",
        "channel_title":    single_result.get("channel_title", ""),
        "thumbnail_url":    f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
        "ad_detected":      single_result.get("ad_detected", False),
        "is_current_video": True,
    })

    for src in pipeline_result.get("sources", []):
        src_vid = src.get("video_id") or src.get("url", "").split("v=")[-1].split("&")[0]
        if src_vid and src_vid not in seen_ids:
            seen_ids.add(src_vid)
            merged_sources.append({
                "video_id":         src_vid,
                "title":            src.get("title", ""),
                "url":              src.get("url", f"https://youtube.com/watch?v={src_vid}"),
                "channel_title":    src.get("channel_title", ""),
                "thumbnail_url":    src.get("thumbnail_url",
                                        f"https://img.youtube.com/vi/{src_vid}/mqdefault.jpg"),
                "ad_detected":      src.get("ad_detected", False),
                "is_current_video": False,
            })

    return JSONResponse({
        "video_id":         video_id,
        "extracted_topic":  extracted_topic,
        "normalized_topic": normalized_topic,
        "single_video": {
            "video_id":          video_id,
            "title":             title,
            "channel_title":     single_result.get("channel_title", ""),
            "thumbnail_url":     f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
            "url":               f"https://youtube.com/watch?v={video_id}",
            "summary":           single_result.get("summary", ""),
            "key_claims":        single_result.get("key_claims", []),
            "ad_score":          single_result.get("ad_score", 0),
            "ad_detected":       single_result.get("ad_detected", False),
            "credibility_score": single_result.get("credibility_score", 0.5),
        },
        "keyword_analysis": {
            "keyword":            pipeline_result.get("keyword", extracted_topic),
            "category":           pipeline_result.get("category", "정보탐색형"),
            "summary_lines":      pipeline_result.get("summary_lines", []),
            "common_facts":       pipeline_result.get("common_facts", []),
            "controversies":      pipeline_result.get("controversies", []),
            "recommended_videos": pipeline_result.get("recommended_videos", []),
        },
        "sources": merged_sources,
    })


async def _full_analyze_single_video(
    video_id: str,
    title: str,
    keyword: str,
) -> dict:
    """
    현재 영상 단독 풀 분석 — analyzer_ai._analyze_single_video 사용.
    YouTube API로 메타데이터 보완, 자막 수집 후 Gemini 1회 호출.
    """
    from agents.analyzer_ai import _analyze_single_video
    from youtube_search import fetch_video_by_id

    # 영상 메타데이터 조회 (channel_title, subscriber_count 등)
    try:
        meta = await asyncio.to_thread(fetch_video_by_id, video_id)
    except Exception:
        meta = {"video_id": video_id, "title": title, "channel_title": "",
                "channel_id": "", "subscriber_count": 0, "description": "",
                "has_paid_placement": None}

    video_info = {
        "video_id":          video_id,
        "title":             meta.get("title") or title,
        "channel_id":        meta.get("channel_id", ""),
        "channel_title":     meta.get("channel_title", ""),
        "subscriber_count":  meta.get("subscriber_count", 0),
        "description":       meta.get("description", ""),
        "has_paid_placement": meta.get("has_paid_placement"),
    }

    # 자막 수집
    transcript = await asyncio.to_thread(_collect_transcript_for_summary, video_id)

    # 단일 영상 분석 (Semaphore 1 — 단독 호출이므로 제한 불필요)
    semaphore = asyncio.Semaphore(1)
    return await _analyze_single_video(keyword, video_info, transcript, semaphore)


def _collect_transcript_for_summary(video_id: str) -> Optional[str]:
    """자막 수집 동기 함수 — asyncio.to_thread 용."""
    from preprocessing import clean_transcript
    raw = get_transcript(video_id)
    if not raw:
        return None
    entries = format_transcript_with_timestamps(raw)
    if not entries:
        return None
    full_text = " ".join(e["text"] for e in entries)
    cleaned = clean_transcript(full_text)
    return cleaned[:15_000] if cleaned else None


# ── 단일 영상 AI 분석 ─────────────────────────────────────────────────────────

@app.get(
    "/ai_analyze/{video_id}",
    response_model=VideoAnalyzeResponse,
    tags=["AI 분석"],
    summary="단일 영상 AI 분석 ✅",
)
async def ai_analyze_video(
    video_id: str,
    query: str = Query("", description="검색 키워드 (컨텍스트용)"),
    user=Depends(get_current_user),
):
    """단일 영상 AI 분석 — index.html의 AI 쟁점 분석 버튼에서 호출."""
    from agents.analyzer_ai import analyze_videos

    cache_key = f"ai_analyze:{video_id}"
    if cache_key in _search_analysis_cache:
        return JSONResponse(_search_analysis_cache[cache_key])

    try:
        keyword = query or video_id
        video_info = {"video_id": video_id, "title": keyword, "channel_title": "", "duration": 0}
        result = await analyze_videos(keyword=keyword, videos=[video_info])

        video_results = result.get("videos", [])
        first = video_results[0] if video_results else {}
        response = {
            "video_id":          video_id,
            "ad_score":          first.get("ad_score", 0),
            "summary":           first.get("summary", ""),
            "key_claims":        first.get("key_claims", []),
            "credibility_score": first.get("credibility_score", 0.5),
            "ad_detected":       first.get("ad_detected", False),
        }
        _search_analysis_cache[cache_key] = response
        return JSONResponse(response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"분석 실패: {str(e)}")


# ── 자막 ──────────────────────────────────────────────────────────────────────

@app.get(
    "/transcript/available/{video_id}",
    response_model=TranscriptAvailableResponse,
    tags=["자막"],
    summary="자막 가용 언어 목록 조회 ✅",
)
def transcript_available(video_id: str):
    langs = list_available_transcripts(video_id)
    return JSONResponse({"video_id": video_id, "available": langs})


@app.get(
    "/transcript/{video_id}",
    response_model=TranscriptResponse,
    tags=["자막"],
    summary="영상 자막 조회 ✅ (video_id는 실제 YouTube video_id 입력)",
)
def transcript(video_id: str):
    if video_id in _transcript_cache:
        return JSONResponse(_transcript_cache[video_id])

    raw = get_transcript(video_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="자막을 찾을 수 없습니다")

    formatted = format_transcript_with_timestamps(raw)
    result = {"video_id": video_id, "count": len(formatted), "transcript": formatted}
    _transcript_cache[video_id] = result
    return JSONResponse(result)


# ── 전처리 ────────────────────────────────────────────────────────────────────

@app.get(
    "/preprocess/{video_id}",
    response_model=PreprocessResponse,
    tags=["전처리"],
    summary="자막 청크 분할 ✅ (video_id는 실제 YouTube video_id 입력)",
)
def preprocess(
    video_id: str,
    channel_id: str = Query("unknown"),
    chunk_size: int = Query(500, ge=100, le=2000),
):
    if video_id in _transcript_cache:
        formatted = _transcript_cache[video_id]["transcript"]
    else:
        raw = get_transcript(video_id)
        if raw is None:
            raise HTTPException(status_code=404, detail="자막을 찾을 수 없습니다")
        formatted = format_transcript_with_timestamps(raw)
        _transcript_cache[video_id] = {
            "video_id":   video_id,
            "count":      len(formatted),
            "transcript": formatted,
        }

    chunks = chunk_transcript(formatted, video_id, channel_id, chunk_size)
    return JSONResponse({
        "video_id":     video_id,
        "total_chunks": len(chunks),
        "chunks":       chunks,
    })


# ── 관리자 ────────────────────────────────────────────────────────────────────

def get_admin(token=Depends(security)):
    """ADMIN_SECRET 검증 의존성"""
    if token.credentials != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="관리자 권한 없음")
    return True


@app.get("/admin.html", tags=["관리자"], include_in_schema=False)
def admin_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "admin.html"))


@app.get(
    "/admin/users",
    response_model=AdminUsersResponse,
    tags=["관리자"],
    summary="전체 유저 목록 🔒 (Authorize에 admin1234 입력)",
)
async def admin_users(
    admin=Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    """전체 유저 목록"""
    from database import User
    result = await db.execute(select(User))
    users = result.scalars().all()
    return {
        "total": len(users),
        "users": [
            {
                "id":            str(u.id),
                "google_id":     u.google_id,
                "email":         u.email,
                "delivery_type": u.delivery_type,
                "created_at":    u.created_at.isoformat(),
            }
            for u in users
        ],
    }


@app.get(
    "/admin/logs",
    response_model=AdminLogsResponse,
    tags=["관리자"],
    summary="오늘 전체 행동 로그 🔒 (Authorize에 admin1234 입력)",
)
async def admin_logs(
    admin=Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    """오늘 전체 행동 로그"""
    from database import BehaviorLog
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    result = await db.execute(
        select(BehaviorLog)
        .where(BehaviorLog.logged_at >= today)
        .order_by(BehaviorLog.logged_at.desc())
    )
    logs = result.scalars().all()
    return {
        "total": len(logs),
        "logs": [
            {
                "user_id":    l.user_id,
                "event_type": l.event_type,
                "keyword":    l.keyword,
                "video_id":   l.video_id,
                "logged_at":  l.logged_at.isoformat(),
            }
            for l in logs
        ],
    }


@app.post(
    "/admin/pipeline/run",
    tags=["관리자"],
    summary="특정 유저 파이프라인 즉시 실행 🔒 (Authorize에 admin1234 입력)",
)
async def admin_run_pipeline(
    user_id: str,
    admin=Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    """특정 유저 파이프라인 즉시 실행 (google_id 기준). 하트 관심 토픽 기반."""
    import json
    from database import Newsletter, UserInterest

    # Issue 8: BehaviorLog 제거 — 하트 관심 토픽(is_active=True)만 사용
    interest_r = await db.execute(
        select(UserInterest.category)
        .where(
            UserInterest.user_id == user_id,
            UserInterest.is_active == True,
        )
        .order_by(UserInterest.created_at.desc())
        .limit(10)
    )
    triggered = [row[0] for row in interest_r.all()]

    if not triggered:
        raise HTTPException(status_code=404, detail="활성 관심 토픽 없음 — 유저가 하트한 토픽이 없습니다")

    newsletter = await run_pipeline(
        user_id=user_id,
        raw_keywords=triggered,
        skip_clustering=True,
    )

    record = Newsletter(
        user_id=user_id,
        subject=newsletter.get("subject", ""),
        content_json=json.dumps(newsletter, ensure_ascii=False),
    )
    db.add(record)
    await db.commit()

    return JSONResponse(newsletter)
