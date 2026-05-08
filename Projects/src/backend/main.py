import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from agents.cluster_ai import cluster_topics
from auth import create_auth_url, exchange_code_for_tokens, create_jwt, verify_jwt
from youtube_search import search_videos, get_subscriptions
from transcript_service import get_transcript, format_transcript_with_timestamps, list_available_transcripts
from preprocessing import chunk_transcript
from shared_cache import search_analysis_cache as _search_analysis_cache_shared
from database import init_db, get_db, Newsletter, UserInterest
from behavior_store import save_behavior, get_today_logs
from trigger import get_triggered_topics
from agents.pipeB_orchestrator import run_pipeline
from scheduler import start_scheduler, stop_scheduler

load_dotenv()
from logger import get_logger
logger = get_logger(__name__)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "../frontend")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "admin1234")
EXTENSION_ID = os.getenv("EXTENSION_ID", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행 (on_event 대체)"""
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Tubify Backend", lifespan=lifespan)
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
# Pipeline A 분석 캐시 — shared_cache 모듈과 동일 객체 참조
# Pipeline B(scheduler)도 이 캐시를 읽어 Gemini 중복 호출 방지
_search_analysis_cache = _search_analysis_cache_shared
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
    # login.html 에 EXTENSION_ID 주입
    with open(os.path.join(FRONTEND_DIR, "login.html"), "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__EXTENSION_ID__", EXTENSION_ID)
    return HTMLResponse(content=html)

@app.get("/home.html")
def home():
    return FileResponse(os.path.join(FRONTEND_DIR, "home.html"))

@app.get("/onboarding.html")
def onboarding():
    with open(os.path.join(FRONTEND_DIR, "onboarding.html"), "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__EXTENSION_ID__", EXTENSION_ID)
    return HTMLResponse(content=html)

@app.get("/dashboard.html")
def dashboard():
    return FileResponse(os.path.join(FRONTEND_DIR, "dashboard.html"))

@app.get("/search_dashboard.html")
def search_dashboard():
    return FileResponse(os.path.join(FRONTEND_DIR, "search_dashboard.html"))

@app.get("/privacy.html")
def privacy():
    return FileResponse(os.path.join(FRONTEND_DIR, "privacy.html"))

@app.get("/terms.html")
def terms():
    return FileResponse(os.path.join(FRONTEND_DIR, "terms.html"))

@app.get("/intro.html")
def intro():
    return FileResponse(os.path.join(FRONTEND_DIR, "intro.html"))

# login.html / home.html 이 참조하는 정적 에셋 (/static/ 마운트와 별개로 루트 경로 노출)
@app.get("/app.js")
def serve_app_js():
    return FileResponse(os.path.join(FRONTEND_DIR, "app.js"), media_type="application/javascript")

@app.get("/style.css")
def serve_style_css():
    return FileResponse(os.path.join(FRONTEND_DIR, "style.css"), media_type="text/css")

@app.get("/home.js")
def serve_home_js():
    return FileResponse(os.path.join(FRONTEND_DIR, "home.js"), media_type="application/javascript")

@app.get("/home.css")
def serve_home_css():
    return FileResponse(os.path.join(FRONTEND_DIR, "home.css"), media_type="text/css")


# ── 헬스체크 ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/auth/login")
def login():
    auth_url, state, code_verifier = create_auth_url()
    _oauth_sessions[state] = code_verifier  # state별로 분리 저장
    logger.debug(f"[login] state 저장: {state}")
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
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
        logger.info(f"[callback] 신규 유저 생성: {user_info['email']}")
    else:
        logger.info(f"[callback] 기존 유저 로그인: {user_info['email']}")

    jwt_token = create_jwt(
        user_id=user_info["google_id"],
        email=user_info["email"],
    )

    # 신규 유저 → 온보딩, 기존 유저 → 메인 페이지
    if not user.initial_intent:
        redirect_url = f"{FRONTEND_URL}/onboarding.html?token={jwt_token}"
    else:
        redirect_url = f"{FRONTEND_URL}/?token={jwt_token}"

    return RedirectResponse(url=redirect_url)


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

_DEFAULT_SEND_TIME = "21:00"


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

# ── 구독 설정 ─────────────────────────────────────────────────────────────────

class SubscribeData(BaseModel):
    delivery_type: str = "email"
    email: Optional[str] = None
    send_time: Optional[str] = None   # "HH:MM" 단일 시간 — 온보딩 Step1에서는 미사용


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
        # 이메일 중복 체크 — 다른 유저가 이미 사용 중인 이메일인지 확인
        dup = await db.execute(
            select(User).where(
                User.email == data.email,
                User.google_id != user["user_id"],
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="이미 다른 계정에서 사용 중인 이메일입니다.",
            )
        db_user.email = data.email
    if data.send_time:
        import re as _re
        if not _re.match(r"^\d{2}:\d{2}$", data.send_time):
            raise HTTPException(status_code=400, detail="send_time은 HH:MM 형식이어야 합니다")
        db_user.send_time = data.send_time

    await db.commit()
    print(f"[subscribe] {user['user_id']} → email / send_time={db_user.send_time}")
    return {"success": True}

# ── 마이페이지: 발송 시간 변경 ────────────────────────────────────────────────

class SendTimeData(BaseModel):
    send_time: str   # "08:00" | "21:00"


@app.patch("/settings/send_time")
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

    logger.info(f"[send-time] {user['user_id']} {prev_time} → {validated_time}")
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
    }


# ── 프로필 조회 / 수정 / 통계 ─────────────────────────────────────────────────

@app.get("/my/profile")
async def my_profile(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """프로필 전체 조회 — 이메일, 발송 시간, 의도 유형, 관심사 카테고리"""
    import json as _json
    from database import User

    result = await db.execute(select(User).where(User.google_id == user["user_id"]))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="유저 없음")

    categories = []
    if db_user.interest_categories:
        try:
            categories = _json.loads(db_user.interest_categories)
        except Exception:
            pass

    # send_time JSON 배열에서 아침(첫 번째)·저녁(마지막) 분리해서 반환
    import json as _json_p
    try:
        times = _json_p.loads(db_user.send_time or '["21:00"]')
        times = times if isinstance(times, list) and times else ["21:00"]
    except Exception:
        times = ["21:00"]
    morning_time = times[0] if len(times) > 1 else "08:00"
    evening_time = times[-1]

    return {
        "email":               db_user.email,
        "send_time":           evening_time,
        "morning_send_time":   morning_time,
        "initial_intent":      db_user.initial_intent,
        "interest_categories": categories,
        "is_subscribed":       db_user.is_subscribed,
        "created_at":          db_user.created_at.isoformat() if db_user.created_at else None,
    }


class ProfileUpdateData(BaseModel):
    send_time:           Optional[str]       = None  # "HH:MM" 저녁 발송 시간
    morning_send_time:   Optional[str]       = None  # "HH:MM" 아침 발송 시간 — 내부적으로 send_time JSON 배열에 합산
    interest_categories: Optional[list[str]] = None  # 관심사 카테고리 목록


@app.put("/my/profile")
async def update_my_profile(
    data: ProfileUpdateData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """발송 시간 / 관심사 수정.
    관심사 변경 시 user_interests에 신규 카테고리만 추가 (기존 weight 유지).
    """
    import re, json as _json
    from database import User
    from datetime import datetime, timezone

    result = await db.execute(select(User).where(User.google_id == user["user_id"]))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="유저 없음")

    time_re = re.compile(r'^\d{2}:\d{2}$')

    # send_time / morning_send_time → JSON 배열로 합산해 저장
    if data.send_time is not None or data.morning_send_time is not None:
        if data.send_time and not time_re.match(data.send_time):
            raise HTTPException(status_code=400, detail="send_time 형식은 HH:MM이어야 합니다.")
        if data.morning_send_time and not time_re.match(data.morning_send_time):
            raise HTTPException(status_code=400, detail="morning_send_time 형식은 HH:MM이어야 합니다.")

        # 기존 배열에서 아침/저녁 추출
        try:
            existing = _json.loads(db_user.send_time or '["21:00"]')
            existing = existing if isinstance(existing, list) and existing else ["21:00"]
        except Exception:
            existing = ["21:00"]
        cur_morning = existing[0] if len(existing) > 1 else "08:00"
        cur_evening = existing[-1]

        new_morning = data.morning_send_time if data.morning_send_time is not None else cur_morning
        new_evening = data.send_time         if data.send_time         is not None else cur_evening
        db_user.send_time = _json.dumps(sorted(list({new_morning, new_evening})), ensure_ascii=False)

    if data.interest_categories is not None:
        db_user.interest_categories = _json.dumps(data.interest_categories, ensure_ascii=False)
        for category in data.interest_categories:
            stmt = (
                pg_insert(UserInterest)
                .values(
                    user_id=user["user_id"],
                    category=category,
                    weight=1,
                    updated_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing(constraint="uq_user_interest_category")
            )
            await db.execute(stmt)

    await db.commit()
    logger.info(f"[profile/update] {user['user_id']} 프로필 수정 완료")
    return {"ok": True}


@app.get("/my/stats")
async def my_stats(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """오늘 활동 통계 — 로그 수, 트리거된 토픽, 총 뉴스레터 수, 마지막 발송 시각"""
    from database import BehaviorLog, Newsletter
    from datetime import datetime, timezone

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    log_count_r = await db.execute(
        select(func.count()).select_from(BehaviorLog).where(
            BehaviorLog.user_id == user["user_id"],
            BehaviorLog.logged_at >= today_start,
        )
    )
    today_log_count = log_count_r.scalar()

    today_logs     = await get_today_logs(db, user_id=user["user_id"])
    triggered_topics = get_triggered_topics(today_logs)

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


@app.get("/my/interests")
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


class ProfileInitData(BaseModel):
    initial_intent:      str            # '유희형'|'지식형'|'구매형'
    interest_categories: list[str] = [] # 온보딩에서 선택한 관심사 목록


@app.post("/profile/init")
async def profile_init(
    data: ProfileInitData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    온보딩 Step2 완료 — initial_intent + interest_categories 저장.
    user_interests 테이블에 weight=1 초기화 (신규 카테고리만).
    """
    import json as _json
    from database import User
    from datetime import datetime, timezone

    if data.initial_intent not in {"유희형", "지식형", "구매형"}:
        raise HTTPException(status_code=400, detail="initial_intent는 유희형|지식형|구매형 중 하나여야 합니다.")

    result = await db.execute(select(User).where(User.google_id == user["user_id"]))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="유저 없음")

    db_user.initial_intent      = data.initial_intent
    db_user.interest_categories = _json.dumps(data.interest_categories, ensure_ascii=False)

    for category in data.interest_categories:
        stmt = (
            pg_insert(UserInterest)
            .values(
                user_id=user["user_id"],
                category=category,
                weight=1,
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(constraint="uq_user_interest_category")
        )
        await db.execute(stmt)

    await db.commit()
    logger.info(f"[profile/init] {user['user_id']} intent={data.initial_intent} categories={data.interest_categories}")
    return {"ok": True}


class HistoryAnalyzeRequest(BaseModel):
    keywords: list[str]

@app.post("/profile/analyze-history")
async def analyze_history(
    body: HistoryAnalyzeRequest,
    user=Depends(get_current_user),
):
    """
    온보딩 Step2 — 유튜브 검색 기록 키워드를 받아 관심 카테고리 + 의도 유형 추론.
    cluster_ai로 토픽 그룹화 → 상위 카테고리명 반환.
    intent_ai로 전체 키워드 의도 분류 → intent_type 반환.
    """
    from agents.cluster_ai import cluster_topics
    from agents.intent_ai import classify_intent

    keywords = [kw.strip() for kw in body.keywords if kw.strip()]
    if not keywords:
        return {"categories": [], "intent_type": "지식형"}

    # 키워드 수 제한 (Gemini 컨텍스트 과부하 방지)
    keywords = keywords[:100]

    clusters, intent_result = await asyncio.gather(
        cluster_topics(keywords, max_topics=8),
        classify_intent(keywords[:10], []),
    )

    categories = [c["topic"] for c in clusters if c.get("topic")]
    intent_type = intent_result.get("intent_type", "지식형")

    logger.info(
        f"[analyze-history] user={user['user_id']} "
        f"keywords={len(keywords)} → categories={categories}, intent={intent_type}"
    )
    return {"categories": categories, "intent_type": intent_type}


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

    logger.info(f"[unsubscribe] {user['user_id']} 수신 해지 완료")
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

    logger.info(f"[resubscribe] {user['user_id']} 수신 재신청 완료")
    return {"success": True, "message": "수신 신청이 완료되었습니다."}


@app.delete("/my/withdraw")
async def withdraw(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    회원 탈퇴 — 사용자 계정 및 관련 데이터 삭제.
    users, user_interests, behavior_logs, newsletters 모두 제거.
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

    newsletter = await run_pipeline(
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


# ── 즉석 검색 분석 ────────────────────────────────────────────────────────────

@app.get("/analyze_search")
async def analyze_search(
    keyword: str = Query(..., min_length=1),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    검색어 기반 즉석 분석 — popup/search_dashboard에서 호출.
    pipeA_orchestrator: selector_ai + intent_ai + analyzer_ai 병렬 실행.
    사용자별 구독 채널/관심사/시청 이력을 개인화 파라미터로 전달.
    (user_id + keyword) 기준 인메모리 캐시로 Gemini 중복 호출 방지.
    """
    from pipeA_orchestrator import run_pipeline_a

    user_id = user.get("sub", "")
    cache_key = f"{user_id}:{keyword}"

    if cache_key in _search_analysis_cache:
        return JSONResponse(_search_analysis_cache[cache_key])

    async with _search_analysis_lock:
        if cache_key in _search_analysis_cache:
            return JSONResponse(_search_analysis_cache[cache_key])

        # 개인화 파라미터 조회
        # TODO: user_subscriptions 테이블 제거됨 — 구독 채널 ID는 빈 리스트로 대체
        interest_result = await db.execute(
            select(UserInterest.category)
            .where(UserInterest.user_id == user_id)
            .order_by(UserInterest.weight.desc())
            .limit(10)
        )
        subscribed_channel_ids = []
        user_categories        = [row[0] for row in interest_result.all()]
        clicked_channel_ids    = []

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


# ── 단일 영상 AI 분석 ─────────────────────────────────────────────────────────

@app.get("/ai_analyze/{video_id}")
async def ai_analyze_video(
    video_id: str,
    query: str = Query("", description="검색 키워드 (컨텍스트용)"),
    user=Depends(get_current_user),
):
    """
    단일 영상 AI 분석 — index.html의 'AI 쟁점 분석' 버튼에서 호출.
    analyzer_ai의 배치 분석을 단일 영상으로 호출.
    """
    from agents.analyzer_ai import analyze_videos

    cache_key = f"ai_analyze:{video_id}"
    if cache_key in _search_analysis_cache:
        return JSONResponse(_search_analysis_cache[cache_key])

    try:
        keyword = query or video_id
        video_info = {"video_id": video_id, "title": keyword, "channel_title": "", "duration": 0}
        result = await analyze_videos(keyword=keyword, videos=[video_info])

        # index.html에서 쓰는 필드만 추출해서 반환
        video_results = result.get("videos", [])
        first = video_results[0] if video_results else {}
        response = {
            "video_id": video_id,
            "ad_score": first.get("ad_score", 0),
            "summary": first.get("summary", ""),
            "key_claims": first.get("key_claims", []),
            "credibility_score": first.get("credibility_score", 0.5),
            "ad_detected": first.get("ad_detected", False),
        }
        _search_analysis_cache[cache_key] = response
        return JSONResponse(response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"분석 실패: {str(e)}")


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

    newsletter = await run_pipeline(
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
