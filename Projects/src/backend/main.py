import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv

from auth import create_flow
from youtube_service import get_subscriptions
from youtube_search import search_videos
from transcript_service import get_transcript, format_transcript_with_timestamps, list_available_transcripts
from preprocessing import chunk_transcript

load_dotenv()

app = FastAPI(title="TechVisibility Backend")

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


@app.get("/")
def root():
    return {"status": "ok"}


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/login")
def login():
    """구글 OAuth 로그인 URL → 브라우저에서 접속"""
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
    """구글 OAuth 콜백"""
    if state != _temp_session.get("state"):
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    flow = create_flow()
    flow.fetch_token(code=code, code_verifier=_temp_session.get("code_verifier"))

    creds = flow.credentials
    _temp_session["credentials"] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }
    return RedirectResponse("http://127.0.0.1:5500/Projects/src/frontend/index.html?loggedIn=1")


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


# ── 트렌드 분석 ──────────────────────────────────────────────────────────────

@app.get("/analyze")
def analyze(
    keyword: str = Query(..., description="분석할 키워드"),
    max_results: int = Query(10, ge=1, le=50),
):
    """
    키워드로 영상 검색 → view_rate(조회수/경과일) 계산 → 상위 5개 반환
    규리(AI파트) 연동용
    """
    videos = search_videos(keyword, max_results)
    if not videos:
        return JSONResponse({"top_videos": [], "message": "검색 결과가 없습니다"})

    now = datetime.now()
    results = []
    for v in videos:
        pub_str = v.get("published_at", "")
        try:
            published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00")).replace(tzinfo=None)
            days = max((now - published_at).days, 1)
        except Exception:
            days = 1

        view_rate = round(v.get("view_count", 0) / days, 2)
        results.append({**v, "days_old": days, "view_rate": view_rate})

    top5 = sorted(results, key=lambda x: x["view_rate"], reverse=True)[:5]
    return JSONResponse({"keyword": keyword, "top_videos": top5})


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
    """
    자막 수집 → 노이즈 제거 → 청크 분할 → 메타데이터 태깅
    민선(DB파트)에게 넘길 청크 데이터 반환
    """
    if video_id in _transcript_cache:
        formatted = _transcript_cache[video_id]["transcript"]
    else:
        raw = get_transcript(video_id)
        if raw is None:
            raise HTTPException(status_code=404, detail="자막을 찾을 수 없습니다")
        formatted = format_transcript_with_timestamps(raw)
        _transcript_cache[video_id] = {"video_id": video_id, "count": len(formatted), "transcript": formatted}

    chunks = chunk_transcript(formatted, video_id, channel_id, chunk_size)

    return JSONResponse({
        "video_id": video_id,
        "total_chunks": len(chunks),
        "chunks": chunks,
    })
