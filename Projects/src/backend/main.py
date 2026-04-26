import os
import asyncio
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
from agents.cluster_ai import cluster_topics
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
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "admin1234")


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
_search_analysis_cache: dict = {}        # {keyword: analysis_result} — 동일 키워드 Gemini 재호출 방지
_search_analysis_lock = asyncio.Lock()   # 동일 키워드 동시 요청 시 중복 Gemini 호출 방지


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

@app.get("/search_dashboard.html")
def search_dashboard():
    return FileResponse(os.path.join(FRONTEND_DIR, "search_dashboard.html"))


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
            send_time="21:00",   # 기본 발송 시간 — 마이페이지에서 변경 가능
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


@app.get("/my/logs")
async def my_logs(
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    내 행동 로그 투명성 엔드포인트 (검색어 로그 공개).
    사용자가 자신의 수집된 행동 데이터를 직접 확인할 수 있도록 제공.

    OUTPUT:
      {
        "total": int,
        "logs": [
          { "event_type": "search"|"watch", "keyword": str,
            "video_id": str|null, "logged_at": ISO8601 }
        ],
        "triggered_topics": [str, ...],   -- 뉴스레터 주제로 사용될 키워드
        "profile_categories": [str, ...], -- 온보딩 프로필 관심사
        "merged_topics": [str, ...]        -- 합산 결과 (실제 사용 키워드)
      }
    """
    import json as _json
    from database import BehaviorLog, User

    # 행동 로그 조회 (최신순)
    result = await db.execute(
        select(BehaviorLog)
        .where(BehaviorLog.user_id == user["user_id"])
        .order_by(BehaviorLog.logged_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()

    # 오늘 로그로 triggered_topics 계산
    today_logs_list = await get_today_logs(db, user_id=user["user_id"])
    triggered_topics = get_triggered_topics(today_logs_list)

    # 프로필 카테고리 조회
    user_result = await db.execute(
        select(User).where(User.google_id == user["user_id"])
    )
    db_user = user_result.scalar_one_or_none()
    profile_categories: list = []
    if db_user and db_user.interest_categories:
        try:
            profile_categories = _json.loads(db_user.interest_categories)
        except Exception:
            profile_categories = []

    # 합산 (scheduler와 동일 로직)
    from scheduler import _merge_keywords
    merged_topics = _merge_keywords(triggered_topics, profile_categories)

    return {
        "total": len(logs),
        "logs": [
            {
                "event_type": log.event_type,
                "keyword":    log.keyword,
                "video_id":   log.video_id,
                "logged_at":  log.logged_at.isoformat(),
            }
            for log in logs
        ],
        "triggered_topics":  triggered_topics,
        "profile_categories": profile_categories,
        "merged_topics":      merged_topics,
    }


# ── 발송 시간 유효성 검사 유틸 ────────────────────────────────────────────────

# 스케줄러가 지원하는 발송 시간 목록 (scheduler.py의 cron job과 일치해야 함)
_VALID_SEND_TIMES = {"08:00", "21:00"}
_DEFAULT_SEND_TIME = "21:00"


def _validate_send_time(send_time: str) -> str:
    """
    발송 시간 유효성 검사 후 정규화된 값 반환.

    - 형식: HH:MM (정확히 5자)
    - 허용값: 08:00 (아침), 21:00 (저녁)

    Raises:
        HTTPException 400: 형식 오류 또는 지원하지 않는 시간
    """
    import re as _re
    if not _re.match(r"^\d{2}:\d{2}$", send_time):
        raise HTTPException(
            status_code=400,
            detail="send_time은 HH:MM 형식이어야 합니다 (예: '08:00', '21:00')",
        )
    if send_time not in _VALID_SEND_TIMES:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 발송 시간입니다. 허용값: {sorted(_VALID_SEND_TIMES)}",
        )
    return send_time


# ── 구독 설정 ─────────────────────────────────────────────────────────────────

class SubscribeData(BaseModel):
    delivery_type: str = "email"
    email: Optional[str] = None
    send_time: Optional[str] = None   # "HH:MM" 형식 (예: "08:00", "21:00"). 미입력 시 "21:00"


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

    db_user.delivery_type = "email"
    if data.email:
        db_user.email = data.email

    # send_time 미입력 시 기본값 보장 — NULL이 절대 저장되지 않도록 함
    raw_time = data.send_time if data.send_time else _DEFAULT_SEND_TIME
    db_user.send_time = _validate_send_time(raw_time)

    await db.commit()
    print(f"[subscribe] {user['user_id']} → email / send_time={db_user.send_time}")
    return {"success": True, "send_time": db_user.send_time}


# ── 마이페이지: 발송 시간 변경 ────────────────────────────────────────────────

class SendTimeData(BaseModel):
    send_time: str   # "08:00" | "21:00"


@app.patch("/my/send-time")
async def update_send_time(
    data: SendTimeData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    마이페이지에서 뉴스레터 발송 시간 변경.

    INPUT:  { "send_time": "08:00" }  또는  { "send_time": "21:00" }
    OUTPUT: { "success": true, "send_time": "08:00" }

    허용값: "08:00" (아침 8시 KST) | "21:00" (저녁 9시 KST, 기본값)
    변경 즉시 다음 배치부터 반영됩니다.
    """
    from database import User

    validated_time = _validate_send_time(data.send_time)

    result = await db.execute(
        select(User).where(User.google_id == user["user_id"])
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    prev_time = db_user.send_time
    db_user.send_time = validated_time
    await db.commit()

    print(f"[send-time] {user['user_id']} {prev_time} → {validated_time}")
    return {"success": True, "send_time": validated_time}


@app.get("/my/settings")
async def get_my_settings(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    마이페이지 설정 조회.
    발송 시간, 수신 동의 여부, 배송 방법 반환.
    """
    from database import User

    result = await db.execute(
        select(User).where(User.google_id == user["user_id"])
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    return {
        "send_time":      db_user.send_time or _DEFAULT_SEND_TIME,
        "is_subscribed":  db_user.is_subscribed,
        "delivery_type":  db_user.delivery_type,
        "email":          db_user.email,
        "valid_send_times": sorted(_VALID_SEND_TIMES),
    }


@app.delete("/my/subscription")
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
    db_user.unsubscribed_at = datetime.now(timezone.utc)
    await db.commit()

    print(f"[unsubscribe] {user['user_id']} 수신 해지 완료")
    return {"success": True, "message": "수신이 해지되었습니다. 언제든 다시 구독할 수 있습니다."}


@app.post("/my/subscription")
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

    print(f"[resubscribe] {user['user_id']} 수신 재신청 완료")
    return {"success": True, "message": "수신 신청이 완료되었습니다."}


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

    # sync 함수 → 이벤트 루프 블로킹 방지
    newsletter = await asyncio.to_thread(
        run_pipeline,
        user_id=user["user_id"],
        raw_keywords=triggered,
    )

    # DB 저장
    record = Newsletter(
        user_id=user["user_id"],
        subject=newsletter.get("subject", ""),
        content_json=json.dumps(newsletter, ensure_ascii=False),
        delivery_type="email",
    )
    db.add(record)
    await db.commit()

    return JSONResponse(newsletter)


# ── 즉석 검색 분석 (Pipeline A) ───────────────────────────────────────────────

@app.get("/analyze_search")
async def analyze_search(
    keyword: str = Query(..., min_length=1),
    user=Depends(get_current_user),
):
    """
    검색어 기반 즉석 분석 — Side Panel / search_dashboard에서 호출.
    루트 orchestrator (selector→[analyzer+category]→dashboard) 실행.
    keyword 기준 인메모리 캐시로 Gemini 중복 호출 방지.

    OUTPUT: {
      keyword, category, layout,
      summary_lines, common_conclusion,
      controversies, recommended_videos, common_facts
    }
    """
    from orchestrator import run_pipeline as run_pipeline_a

    # 캐시 히트 (Lock 없이 먼저 체크 — 이미 저장된 경우 빠른 반환)
    if keyword in _search_analysis_cache:
        return JSONResponse(_search_analysis_cache[keyword])

    # Lock으로 동일 키워드 동시 요청 시 중복 Gemini 호출 방지
    async with _search_analysis_lock:
        # Lock 진입 후 재확인 (다른 요청이 먼저 완료했을 수 있음)
        if keyword in _search_analysis_cache:
            return JSONResponse(_search_analysis_cache[keyword])

        def _run():
            try:
                return run_pipeline_a(keyword)
            except ValueError:
                # 검색 결과 없음
                return {
                    "keyword": keyword,
                    "category": "정보탐색형",
                    "layout": "summary_focus",
                    "summary_lines": [],
                    "common_conclusion": "",
                    "controversies": [],
                    "recommended_videos": [],
                    "common_facts": [],
                }

        result = await asyncio.to_thread(_run)
        _search_analysis_cache[keyword] = result

    return JSONResponse(result)


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


# ── 관리자 ────────────────────────────────────────────────────────────────────

def get_admin(token=Depends(security)):
    """ADMIN_SECRET 검증 의존성"""
    if token.credentials != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="관리자 권한 없음")
    return True


@app.get("/admin.html")
def admin_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "admin.html"))


@app.get("/admin/users")
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


@app.get("/admin/logs")
async def admin_logs(
    admin=Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    """오늘 전체 행동 로그"""
    from database import BehaviorLog
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
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


@app.post("/admin/pipeline/run")
async def admin_run_pipeline(
    user_id: str,
    admin=Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    """특정 유저 파이프라인 즉시 실행 (google_id 기준)"""
    import asyncio, json
    from database import User, Newsletter

    logs      = await get_today_logs(db, user_id=user_id)
    triggered = get_triggered_topics(logs)

    if not triggered:
        raise HTTPException(status_code=404, detail="트리거된 주제 없음")

    # sync 함수 → 이벤트 루프 블로킹 방지
    newsletter = await asyncio.to_thread(
        run_pipeline,
        user_id=user_id,
        raw_keywords=triggered,
    )

    # DB 저장
    record = Newsletter(
        user_id=user_id,
        subject=newsletter.get("subject", ""),
        content_json=json.dumps(newsletter, ensure_ascii=False),
        delivery_type="email",
    )
    db.add(record)
    await db.commit()

    return JSONResponse(newsletter)


# ── 프로필 초기화 (PHASE 1) ───────────────────────────────────────────────────

class ProfileInitData(BaseModel):
    initial_intent: str                    # '유희형' | '지식형' | '구매형'
    interest_categories: list[str] = []   # 관심사 카테고리 목록


class HistoryAnalysisRequest(BaseModel):
    keywords: list[str]


@app.post("/profile/init")
async def profile_init(
    data: ProfileInitData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    온보딩 완료 시 초기 관심사 프로필 저장.
    initial_intent와 interest_categories를 users 테이블에 저장한다.
    """
    import json as _json
    from database import User

    result = await db.execute(
        select(User).where(User.google_id == user["user_id"])
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    if data.initial_intent not in ("유희형", "지식형", "구매형"):
        raise HTTPException(status_code=400, detail="initial_intent는 유희형|지식형|구매형 중 하나여야 합니다")

    db_user.initial_intent      = data.initial_intent
    db_user.interest_categories = _json.dumps(data.interest_categories, ensure_ascii=False)
    await db.commit()

    print(f"[profile/init] {user['user_id']} → 의도={data.initial_intent}, 카테고리={data.interest_categories}")
    return {"success": True}


@app.post("/profile/analyze-history")
async def analyze_history(
    data: HistoryAnalysisRequest,
    user=Depends(get_current_user),
):
    """
    익스텐션이 chrome.history API로 수집한 유튜브 검색어를 받아
    cluster_ai + intent_ai로 초기 관심사 프로필을 추론한다.

    INPUT:  {"keywords": ["파이썬 강의", "아이폰 16 리뷰", ...]}
    OUTPUT: {"intent_type": "지식형", "categories": ["파이썬", "스마트폰"]}
    """
    from agents.cluster_ai import cluster_topics
    from agents.intent_ai import classify_intent

    keywords = [k.strip() for k in data.keywords if k.strip()]
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords가 비어 있습니다")

    clusters      = await asyncio.to_thread(cluster_topics, keywords, 5)
    categories    = [c["topic"] for c in clusters]
    intent_result = await asyncio.to_thread(classify_intent, keywords, [])
    intent_type   = intent_result.get("intent_type", "지식형")

    re    """특정 유저 파이프라인 즉시 실행 (google_id 기준)"""
    import asyncio, json
    from database import User, Newsletter

    logs      = await get_today_logs(db, user_id=user_id)
    triggered = get_triggered_topics(logs)

    if not triggered:
        raise HTTPException(status_code=404, detail="트리거된 주제 없음")

    newsletter = await asyncio.to_thread(
        run_pipeline,
        user_id=user_id,
        raw_keywords=triggered,
    )

    record = Newsletter(
        user_id=user_id,
        subject=newsletter.get("subject", ""),
        content_json=json.dumps(newsletter, ensure_ascii=False),
        delivery_type="email",
    )
    db.add(record)
    await db.commit()

    return JSONResponse(newsletter)


# ── 프로필 초기화 (PHASE 1) ───────────────────────────────────────────────────

class ProfileInitData(BaseModel):
    initial_intent: str
    interest_categories: list[str] = []


class HistoryAnalysisRequest(BaseModel):
    keywords: list[str]


@app.post("/profile/init")
async def profile_init(
    data: ProfileInitData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    온보딩 완료 시 초기 관심사 프로필 저장.
    initial_intent와 interest_categories를 users 테이블에 저장한다.
    """
    import json as _json
    from database import User

    result = await db.execute(
        select(User).where(User.google_id == user["user_id"])
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    if data.initial_intent not in ("유희형", "지식형", "구매형"):
        raise HTTPException(status_code=400, detail="initial_intent는 유희형|지식형|구매형 중 하나여야 합니다")

    db_user.initial_intent      = data.initial_intent
    db_user.interest_categories = _json.dumps(data.interest_categories, ensure_ascii=False)
    await db.commit()

    print(f"[profile/init] {user['user_id']} -> 의도={data.initial_intent}, 카테고리={data.interest_categories}")
    return {"success": True}


@app.post("/profile/analyze-history")
async def analyze_history(
    data: HistoryAnalysisRequest,
    user=Depends(get_current_user),
):
    """
    익스텐션이 chrome.history API로 수집한 유튜브 검색어를 받아
    cluster_ai + intent_ai로 초기 관심사 프로필을 추론한다.

    INPUT:  {"keywords": ["파이썬 강의", "아이폰 16 리뷰", ...]}
    OUTPUT: {"intent_type": "지식형", "categories": ["파이썬", "스마트폰"]}
    """
    from agents.cluster_ai import cluster_topics
    from agents.intent_ai import classify_intent

    keywords = [k.strip() for k in data.keywords if k.strip()]
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords가 비어 있습니다")

    clusters      = await asyncio.to_thread(cluster_topics, keywords, 5)
    categories    = [c["topic"] for c in clusters]
    intent_result = await asyncio.to_thread(classify_intent, keywords, [])
    intent_type   = intent_result.get("intent_type", "지식형")

    return {"intent_type": intent_type, "categories": categories}
