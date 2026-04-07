import os
from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from typing import List, Optional
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv

from auth import create_flow, exchange_code_for_tokens, create_jwt, verify_jwt
from youtube_service import get_subscriptions
from youtube_search import search_videos
from transcript_service import get_transcript, format_transcript_with_timestamps, list_available_transcripts
from preprocessing import chunk_transcript
from orchestrator import run_pipeline

load_dotenv()

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "../frontend")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")

app = FastAPI(title="TechVisibility Backend")
security = HTTPBearer()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 테스트용 임시 세션 저장 (실제 서비스에선 Redis 등으로 교체)
_temp_session: dict = {}

# 자막 인메모리 캐시 (video_id → 결과)
_transcript_cache: dict = {}


# ── JWT 인증 의존성 ────────────────────────────────────────────────────────────

def get_current_user(token=Depends(security)):
    """
    Authorization: Bearer <JWT> 헤더 검증
    익스텐션의 /collect 등 보호된 엔드포인트에서 사용
    """
    user = verify_jwt(token.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user  # {"user_id": ..., "email": ...}

# ── 정적 파일 서빙 ────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# ── 헬스체크 ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/login")
def login():
    """구글 OAuth 로그인 URL → 브라우저에서 접속"""
    from auth import create_flow
    flow = create_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _temp_session["state"] = state
    _temp_session["code_verifier"] = flow.code_verifier
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
def callback(code: str, state: str):
    """
    구글 OAuth 콜백
    1. code → 구글 토큰 교환 (exchange_code_for_tokens 한 번만 호출)
    2. 우리 서버 JWT 발급
    3. 프론트로 리다이렉트 (쿼리스트링에 JWT 포함)
    """
    if state != _temp_session.get("state"):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # ★ exchange_code_for_tokens 안에서 flow.fetch_token까지 처리
    #    (기존 코드의 중복 fetch_token 제거)
    user_info = exchange_code_for_tokens(code)

    # 구글 credentials를 세션에 저장 (유튜브 API 호출용)
    _temp_session["credentials"] = user_info.get("credentials")
    _temp_session["user_info"] = user_info

    # ★ JWT 발급
    jwt_token = create_jwt(
        user_id=user_info["google_id"],
        email=user_info["email"],
    )
     # ★ 프론트로 리다이렉트 — onboarding.html이 토큰을 받아 익스텐션에 전달
    return RedirectResponse(
        url=f"{FRONTEND_URL}/onboarding.html?token={jwt_token}"
    )


@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    """현재 로그인된 사용자 정보 확인 (JWT 검증 테스트용)"""
    return {"user_id": user["user_id"], "email": user["email"]}

# ── 행동 데이터 수집 (익스텐션 → 백엔드) ──────────────────────────────────────

class CollectData(BaseModel):
    event_type: str          # "search" | "watch"
    keyword: str
    video_id: Optional[str] = None

@app.post("/collect")
def collect(data: CollectData, user=Depends(get_current_user)):
    """
    크롬 익스텐션이 유튜브 검색/시청 이벤트를 전송
    Authorization: Bearer <JWT> 헤더 필수
    """
    print(f"[collect] user={user['user_id']} | {data.event_type} | {data.keyword}")
    # TODO: behavior_store.save() 연결 (세션 1에서 구현)
    return {"saved": True, "user_id": user["user_id"]}

# ── YouTube 사용자 데이터 ────────────────────────────────────────────────────

@app.get("/subscriptions")
def subscriptions():
    """로그인 사용자의 YouTube 구독 채널 목록"""
    creds_data = _temp_session.get("credentials")
    if not creds_data:
        raise HTTPException(status_code=401, detail="로그인 필요: /auth/login 먼저 방문하세요")

    creds = Credentials(
        token=creds_data["token"],
        refresh_token=creds_data["refresh_token"],
        token_uri=creds_data["token_uri"],
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=creds_data["scopes"],
    )
    subs = get_subscriptions(creds)
    return JSONResponse({"count": len(subs), "subscriptions": subs})


# ── YouTube 검색 ─────────────────────────────────────────────────────────────

@app.get("/search")
def search(
    keyword: str = Query(..., description="검색 키워드"),
    max_results: int = Query(10, ge=1, le=50),
):
    """키워드로 YouTube 영상 검색 + 메타데이터 반환"""
    results = search_videos(keyword, max_results)
    return JSONResponse({"count": len(results), "videos": results})


# ── AI 분석 메인 엔드포인트 ───────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    keyword: str
    subscribed_channel_ids: List[str] = []


@app.post("/analyze_search")
def analyze_search(req: AnalyzeRequest):
    keyword = req.keyword.strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="keyword는 비어 있을 수 없습니다")

    try:
        result = run_pipeline(
            keyword=keyword,
            subscribed_channel_ids=req.subscribed_channel_ids,
        )
        return JSONResponse(result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"!!! [analyze_search 오류] {e}")
        raise HTTPException(status_code=500, detail=f"분석 중 오류 발생: {str(e)}")

# ── 자막 수집 ─────────────────────────────────────────────────────────────────

@app.get("/transcript/available/{video_id}")
def transcript_available(video_id: str):
    """영상에서 사용 가능한 자막 언어 목록 확인"""
    langs = list_available_transcripts(video_id)
    return JSONResponse({"video_id": video_id, "available": langs})


@app.get("/transcript/{video_id}")
def transcript(video_id: str):
    """영상 자막 + timestamp 반환. 자막 없으면 404. 캐시 히트 시 즉시 반환."""
    if video_id in _transcript_cache:
        return JSONResponse(_transcript_cache[video_id])

    raw = get_transcript(video_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="자막을 찾을 수 없습니다")

    formatted = format_transcript_with_timestamps(raw)
    result = {"video_id": video_id, "count": len(formatted), "transcript": formatted}
    _transcript_cache[video_id] = result
    return JSONResponse(result)


# ── 전처리 파이프라인 ──────────────────────────────────────────────────────────

@app.get("/preprocess/{video_id}")
def preprocess(
    video_id: str,
    channel_id: str = Query("unknown"),
    chunk_size: int = Query(500, ge=100, le=2000),
):
    """자막 수집 → 노이즈 제거 → 청크 분할 → 메타데이터 태깅"""
    if video_id in _transcript_cache:
        formatted = _transcript_cache[video_id]["transcript"]
    else:
        raw = get_transcript(video_id)
        if raw is None:
            raise HTTPException(status_code=404, detail="자막을 찾을 수 없습니다")
        formatted = format_transcript_with_timestamps(raw)
        _transcript_cache[video_id] = {
            "video_id": video_id,
            "count": len(formatted),
            "transcript": formatted,
        }

    chunks = chunk_transcript(formatted, video_id, channel_id, chunk_size)
    return JSONResponse({
        "video_id": video_id,
        "total_chunks": len(chunks),
        "chunks": chunks,
    })
