# APScheduler 기반 뉴스레터 배치 실행기
# feature/interest-newsletter-scheduler: 발송 기준을 하트 관심 토픽으로 변경
# 행동기록(BehaviorLog) 기반 fallback 제거 — 하트 관심사 0개면 발송 skip
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from database import AsyncSessionLocal, User, Newsletter, UserInterest
from agents.pipeB_orchestrator import run_pipeline
from mailer import send_email

from logger import get_logger
logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _parse_send_times(raw: str) -> List[str]:
    """send_time JSON 배열 문자열 → HH:MM 리스트. 파싱 실패 시 ["21:00"] 반환."""
    try:
        times = json.loads(raw or '["21:00"]')
        return times if isinstance(times, list) else ["21:00"]
    except (json.JSONDecodeError, TypeError):
        return ["21:00"]


async def _already_sent_in_window(db, user_id: str, hours: int = 10) -> bool:
    """최근 N시간 이내에 발송된 뉴스레터가 있으면 True (슬롯 중복 방지)."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    result = await db.execute(
        select(Newsletter).where(
            Newsletter.user_id == user_id,
            Newsletter.delivered_at >= cutoff,
        )
    )
    return result.scalar_one_or_none() is not None


async def _get_active_interest_topics(db, user_id: str) -> List[str]:
    """
    사용자의 활성 관심 토픽 목록을 normalized_topic 기준으로 중복 제거해 반환.
    정렬: created_at 오름차순 (먼저 하트한 토픽 우선).
    """
    result = await db.execute(
        select(UserInterest)
        .where(
            UserInterest.user_id  == user_id,
            UserInterest.is_active == True,  # noqa: E712
        )
        .order_by(UserInterest.created_at.asc())
    )
    interests = result.scalars().all()

    # normalized_topic 기준 중복 제거
    seen: set = set()
    topics: List[str] = []
    for i in interests:
        key = (i.normalized_topic or i.category).strip().lower()
        if key and key not in seen:
            seen.add(key)
            topics.append(i.category)

    return topics


async def _save_newsletter(
    db,
    user: User,
    newsletter: Dict[str, Any],
) -> Newsletter:
    """뉴스레터를 DB에 저장하고 ORM 객체를 반환."""
    record = Newsletter(
        user_id=user.google_id,
        subject=newsletter.get("subject", ""),
        content_json=json.dumps(newsletter, ensure_ascii=False),
        delivery_status="generated",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def _deliver_newsletter(
    user: User,
    newsletter: Dict[str, Any],
) -> Dict[str, Any]:
    """이메일 발송 후 결과 딕셔너리 반환."""
    try:
        result = send_email(
            user_email=user.email,
            newsletter=newsletter,
            newsletter_type="interest",
        )
        return result if result else {"success": True}
    except Exception as e:
        logger.error(f"[deliver] 예외 발생: {e}")
        return {"success": False, "error": str(e)}


# ── 배치 실행 ─────────────────────────────────────────────────────────────────

async def _run_batch_for_send_time(send_time: str) -> None:
    logger.info(f"[scheduler] {send_time} batch start")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.is_subscribed == True)  # noqa: E712
        )
        all_users = result.scalars().all()

        # send_time JSON 배열에 현재 시각이 포함된 유저만 추출
        users = [u for u in all_users if send_time in _parse_send_times(u.send_time)]
        logger.info(f"[scheduler] {send_time} → {len(users)}명 대상")

        for user in users:
            try:
                # ── 중복 발송 방지 ─────────────────────────────────────────
                if await _already_sent_in_window(db, str(user.google_id), hours=10):
                    logger.warning(f"  [skip] {user.email} — 최근 10시간 내 발송 이력 있음")
                    continue

                # ── 하트 관심 토픽 조회 ────────────────────────────────────
                topics = await _get_active_interest_topics(db, str(user.google_id))

                if not topics:
                    logger.info(f"  [skip] {user.email} — 활성 관심 토픽 없음")
                    continue

                logger.info(f"  [run] {user.email} — 관심 토픽 {len(topics)}개: {topics}")

                # ── 파이프라인 실행 (관심 토픽 기반) ─────────────────────
                newsletter = await run_pipeline(
                    user_id=str(user.google_id),
                    raw_keywords=topics,
                    skip_clustering=True,   # 하트 토픽은 이미 정제됨 — 클러스터링 불필요
                )

                # ── 뉴스레터 저장 ─────────────────────────────────────────
                nl_record = await _save_newsletter(db, user, newsletter)

                # ── 이메일 발송 ───────────────────────────────────────────
                deliver_result = await _deliver_newsletter(user, newsletter)
                if deliver_result.get("success", True):
                    nl_record.delivery_status = "sent"
                    logger.info(f"  [done] {user.email}")
                else:
                    nl_record.delivery_status = "failed"
                    nl_record.error_message = deliver_result.get("error", "Unknown error")
                    logger.error(f"  [fail] {user.email} — {nl_record.error_message}")

                await db.commit()

            except Exception as e:
                logger.error(f"  [error] {user.email} — {e}")
                continue

    logger.info(f"[scheduler] {send_time} batch done")


# ── 스케줄러 실행 ─────────────────────────────────────────────────────────────

async def per_minute_batch():
    """매분: 현재 KST HH:MM이 send_time과 일치하는 유저에게 발송."""
    now_hhmm = datetime.now(KST).strftime("%H:%M")
    await _run_batch_for_send_time(now_hhmm)


def start_scheduler():
    scheduler.add_job(
        per_minute_batch,
        CronTrigger(minute="*", timezone="Asia/Seoul"),
        id="per_minute_batch",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[scheduler] 스케줄러 시작 — 하트 관심 토픽 기반 발송")


def stop_scheduler():
    scheduler.shutdown()
    logger.info("[scheduler] 스케줄러 종료")


# Issue 8: _merge_keywords, _update_user_interests DEPRECATED 함수 제거 완료
