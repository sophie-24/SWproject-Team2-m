import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from auth import create_auth_url, exchange_code_for_tokens, create_jwt, verify_jwt
from youtube_service import get_subscriptions
from youtube_search import search_videos
from transcript_service import get_transcript, format_transcript_with_timestamps, list_available_transcripts
from preprocessing import chunk_transcript
from database import init_db, get_db, Newsletter
from collector.behavior_store import save_behavior, get_today_logs
from collector.trigger import get_triggered_topics
from agents.orchestrator import run_pipeline
from scheduler import start_scheduler, stop_scheduler

load_dotenv()

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "../frontend")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행 (on_event 대체)"""
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="TechVisibility Backend", lifespan=lifespan)
security = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙 (frontend/ 폴더)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# OAuth 진행 중인 요청별 PKCE 데이터 (state → code_verifier)
# Redis 도입 전 임시 구현 — 단일 워커 환경에서만 안전
_oauth_sessions: dict[str, str] = {}  # {state: code_verifier}
_oauth_credentials: dict[str, dict] = {}  # {state: credentials}

_transcript_cache: dict = {}


# ── JWT 인증 의존성 ────────────────────────────────────────────────────────────

def get_current_user(token=Depends(security)):
    user = verify_jwt(token.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


# ── 정적 파일 ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/onboarding.html")
def onboarding():
    return FileResponse(os.path.join(FRONTEND_DIR, "onboarding.html"))

@app.get("/dashboard.html")
def dashboard():
    return FileResponse(os.path.join(FRONTEND_DIR, "dashboard.html"))


# ── 헬스체크 ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/login")
def login():
    auth_url, state, code_verifier = create_auth_url()
    _oauth_sessions[state] = code_verifier  # state별로 분리 저장
    print(f"[login] state 저장: {state}")
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
async def callback(
    code: str, 
    state: str,
    db : AsyncSession = Depends(get_db)
):
    print(f"[callback] state 수신: {state}")

    code_verifier = _oauth_sessions.pop(state, None)  # 사용 후 즉시 제거
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    user_info = exchange_code_for_tokens(code, code_verifier)
    _oauth_credentials[state] = user_info.get("credentials")
    from database import User
    from sqlalchemy import select

    result = await db.execute(
        select(User).where(User.google_id == user_info["google_id"])
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            google_id=user_info["google_id"],
            email=user_info["email"],
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"[callback] 신규 유저 생성: {user_info['email']}")
    else:
        print(f"[callback] 기존 유저 로그인: {user_info['email']}")

    jwt_token = create_jwt(
        user_id=user_info["google_id"],
        email=user_info["email"],
    )
    return RedirectResponse(
        url=f"{FRONTEND_URL}/onboarding.html?token={jwt_token}"
    )


@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    return {"user_id": user["user_id"], "email": user["email"]}


# ── 행동 데이터 수집 ───────────────────────────────────────────────────────────

class CollectData(BaseModel):
    event_type: str        # "search" | "watch"
    keyword: str
    video_id: Optional[str] = None


@app.post("/collect")
async def collect(
    data: CollectData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await save_behavior(
        db=db,
        user_id=user["user_id"],
        event_type=data.event_type,
        keyword=data.keyword,
        video_id=data.video_id,
    )
    return result

@app.get("/collect/today")
async def today_logs(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """오늘 수집된 행동 로그 확인용"""
    logs = await get_today_logs(db, user_id=user["user_id"])
    triggered = get_triggered_topics(logs)
    return {
        "total_logs": len(logs),
        "logs": logs,
        "triggered_topics": triggered,
    }
# ── 구독 설정 ─────────────────────────────────────────────────────────────────

class SubscribeData(BaseModel):
    delivery_type: str     # "kakao" | "email"
    email: Optional[str] = None
    kakao_uuid: Optional[str] = None


@app.post("/subscribe")
async def subscribe(
    data: SubscribeData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """onboarding.html에서 수신 방법 저장 — users 테이블 업데이트"""
    from database import User

    result = await db.execute(
        select(User).where(User.google_id == user["user_id"])
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    db_user.delivery_type = data.delivery_type
    if data.delivery_type == "kakao" and data.kakao_uuid:
        db_user.kakao_uuid = data.kakao_uuid
    if data.delivery_type == "email" and data.email:
        db_user.email = data.email

    await db.commit()
    print(f"[subscribe] {user['user_id']} → {data.delivery_type} 저장 완료")
    return {"success": True}


# ── YouTube ───────────────────────────────────────────────────────────────────

@app.get("/subscriptions")
def subscriptions(user=Depends(get_current_user)):
    # 가장 최근 OAuth credentials 탐색 (단일 워커 환경 한정)
    creds_data = next(iter(_oauth_credentials.values()), None) if _oauth_credentials else None
    if not creds_data:
        raise HTTPException(status_code=401, detail="OAuth 재로그인 필요 (구독 목록 조회용)")

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


@app.get("/search")
def search(
    keyword: str = Query(...),
    max_results: int = Query(10, ge=1, le=50),
):
    results = search_videos(keyword, max_results)
    return JSONResponse({"count": len(results), "videos": results})


# ── 뉴스레터 ──────────────────────────────────────────────────────────────────

@app.get("/newsletter/history")
async def newsletter_history(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """내 뉴스레터 히스토리 조회 (dashboard.html에서 사용)"""
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
                "id":            str(n.id),
                "subject":       n.subject,
                "content_json":  n.content_json,
                "delivered_at":  n.delivered_at.isoformat(),
                "delivery_type": n.delivery_type,
            }
            for n in newsletters
        ]
    })


@app.post("/newsletter/send-now")
async def send_now(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """즉시 발송 테스트용"""
    import asyncio
    from database import User, Newsletter
    import json

    today_logs = await get_today_logs(db, user_id=user["user_id"])
    triggered  = get_triggered_topics(today_logs)

    if not triggered:
        raise HTTPException(status_code=404, detail="트리거된 주제 없음 — 유튜브에서 검색해보세요")

    # 사용자 delivery_type 조회
    result = await db.execute(
        select(User).where(User.google_id == user["user_id"])
    )
    db_user = result.scalar_one_or_none()
    delivery_type = db_user.delivery_type if db_user else "email"

    # sync 함수 → 이벤트 루프 블로킹 방지
    newsletter = await asyncio.to_thread(
        run_pipeline,
        user_id=user["user_id"],
        raw_keywords=triggered,
        delivery_type=delivery_type,
    )

    # DB 저장
    record = Newsletter(
        user_id=user["user_id"],
        subject=newsletter.get("subject", ""),
        content_json=json.dumps(newsletter, ensure_ascii=False),
        delivery_type=delivery_type,
    )
    db.add(record)
    await db.commit()

    return JSONResponse(newsletter)


# ── 자막 ──────────────────────────────────────────────────────────────────────

@app.get("/transcript/available/{video_id}")
def transcript_available(video_id: str):
    langs = list_available_transcripts(video_id)
    return JSONResponse({"video_id": video_id, "available": langs})


@app.get("/transcript/{video_id}")
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

@app.get("/preprocess/{video_id}")
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