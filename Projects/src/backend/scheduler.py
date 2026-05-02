# APScheduler 기반 Pipeline B 배치 실행기 — 사용자별 send_time에 뉴스레터 생성·발송
import os
import json
import uuid
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
<<<<<<< Updated upstream
from sqlalchemy import select
=======
from datetime import date as date_type
from sqlalchemy import select, func, or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
>>>>>>> Stashed changes
from dotenv import load_dotenv

from database import AsyncSessionLocal, User, BehaviorLog, Newsletter, ReportBatch, UserInterest, UserSubscription
from behavior_store import get_today_logs
from trigger import get_triggered_topics
from agents.orchestrator import run_pipeline
from mailer import send_email

load_dotenv()
from logger import get_logger
logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


# -- util --

async def _get_subscribed_channel_ids(user_id: str) -> List[str]:
    """DB에서 유저의 구독 채널 ID 목록 조회."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserSubscription.channel_id)
            .where(UserSubscription.user_id == user_id)
        )
        return [row[0] for row in result.all()]


def _get_profile_keywords(user: User) -> List[str]:
    if not user.interest_categories:
        return []
    try:
        categories = json.loads(user.interest_categories)
        return categories if isinstance(categories, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _merge_keywords(triggered: List[str], profile: List[str]) -> List[str]:
    seen: set = set()
    merged: List[str] = []
    for kw in triggered + profile:
        kw_lower = kw.strip().lower()
        if kw_lower and kw_lower not in seen:
            seen.add(kw_lower)
            merged.append(kw.strip())
    return merged[:10]


async def _save_newsletter(
    db,
    user: User,
    newsletter: Dict[str, Any],
    batch_id: Optional[uuid.UUID] = None,
) -> Newsletter:
    """뉴스레터를 DB에 저장하고 ORM 객체를 반환. delivery_status는 'pending'으로 시작."""
    record = Newsletter(
        user_id=user.google_id,
        subject=newsletter.get("subject", ""),
        content_json=json.dumps(newsletter, ensure_ascii=False),
        delivery_type=user.delivery_type,
        delivery_status="pending",
        batch_id=batch_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def _deliver_newsletter(user: User, newsletter: Dict[str, Any]) -> Dict[str, Any]:
    """이메일 발송 후 결과 딕셔너리 반환. {"success": bool, "error": str(optional)}"""
    try:
        result = send_email(user_email=user.email, newsletter=newsletter)
        if result is None:
            return {"success": True}
        return result
    except Exception as e:
        logger.error(f"[deliver] 예외 발생: {e}")
        return {"success": False, "error": str(e)}


async def _update_user_interests(db, user_id: str, topics: List[str]) -> None:
    """Pipeline B 실행 후 cluster_ai 결과 토픽으로 user_interests weight 누적.
    이미 존재하는 카테고리면 weight+1, 없으면 weight=1로 신규 생성.
    Gemini 추가 호출 없음 -- merged_topics 재활용.
    """
    for topic in topics:
        stmt = (
            pg_insert(UserInterest)
            .values(
                user_id=user_id,
                category=topic,
                weight=1,
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                constraint="uq_user_interest_category",
                set_={
                    "weight": UserInterest.weight + 1,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
        )
        await db.execute(stmt)
    await db.commit()


<<<<<<< Updated upstream
async def _run_batch_for_send_time(send_time: str) -> None:
    """
    특정 send_time(HH:MM)에 설정된 사용자들만 배치 실행.
    daily_batch()와 동일 로직이지만 send_time 필터 적용.
    """
    print(f"[scheduler] {send_time} 배치 시작")
=======
# -- duplicate send guard --

async def _already_sent_in_window(db, user_id: str, hours: int = 10) -> bool:
    """최근 N시간 이내에 발송된 뉴스레터가 있으면 True (오전/오후 슬롯 중복 방지)"""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await db.execute(
        select(Newsletter).where(
            Newsletter.user_id == user_id,
            Newsletter.delivered_at >= cutoff,
        )
    )
    return result.scalar_one_or_none() is not None


# -- batch --

async def _run_batch_for_send_time(send_time: str) -> None:
    logger.info(f"[scheduler] {send_time} batch start")
>>>>>>> Stashed changes

    async with AsyncSessionLocal() as db:
        if send_time == "21:00":
            time_filter = or_(
                User.send_time == send_time,
                User.send_time == None,  # noqa: E711
                User.morning_send_time == send_time,
            )
        else:
            time_filter = or_(
                User.send_time == send_time,
                User.morning_send_time == send_time,
            )

        result = await db.execute(
<<<<<<< Updated upstream
            select(User).where(User.send_time == send_time)
        )
        users = result.scalars().all()
        print(f"[scheduler] {send_time} 대상 {len(users)}명")
=======
            select(User).where(
                time_filter,
                User.is_subscribed == True,  # noqa: E712
            )
        )
        users = result.scalars().all()
        logger.info(f"[scheduler] {send_time} -> {len(users)} users")
>>>>>>> Stashed changes

        for user in users:
            batch: Optional[ReportBatch] = None
            try:
<<<<<<< Updated upstream
                today_logs = await get_today_logs(db, user_id=str(user.google_id))
=======
                if await _already_sent_in_window(db, str(user.google_id), hours=10):
                    logger.warning(f"  [skip] {user.email} already sent today")
                    continue

                # 1. ReportBatch 생성
                batch = ReportBatch(user_id=str(user.google_id))
                db.add(batch)
                await db.commit()
                await db.refresh(batch)
>>>>>>> Stashed changes

                # 2. 오늘의 pending 로그 ID 수집
                today_start = datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                log_id_result = await db.execute(
                    select(BehaviorLog.id).where(
                        BehaviorLog.user_id == str(user.google_id),
                        BehaviorLog.logged_at >= today_start,
                        BehaviorLog.status == "pending",
                    )
                )
                log_ids = [row[0] for row in log_id_result.all()]

                # 3. 트리거 분석 및 토픽 병합
                today_logs = await get_today_logs(db, user_id=str(user.google_id))
                triggered_topics = get_triggered_topics(today_logs)
                profile_keywords = _get_profile_keywords(user)
                merged_topics = _merge_keywords(triggered_topics, profile_keywords)

                if not merged_topics:
                    logger.warning(f"  [skip] {user.email} no topics")
                    batch.status = "failed"
                    batch.finished_at = datetime.now(timezone.utc)
                    await db.commit()
                    continue

                # 4. 사용한 로그를 processed 로 마킹
                if log_ids:
                    await db.execute(
                        update(BehaviorLog)
                        .where(BehaviorLog.id.in_(log_ids))
                        .values(status="processed", batch_id=batch.id)
                    )
                    await db.commit()

<<<<<<< Updated upstream
                triggered_topics = merged_topics

=======
                # 5. 파이프라인 실행
>>>>>>> Stashed changes
                subscribed_channel_ids = await _get_subscribed_channel_ids(str(user.google_id))
                newsletter = await run_pipeline(
                    user_id=str(user.google_id),
                    raw_keywords=triggered_topics,
                    subscribed_channel_ids=subscribed_channel_ids,
                    initial_intent=user.initial_intent,
                    today_logs=today_logs,
                )

                # 6. 뉴스레터 저장 (delivery_status='pending')
                nl_record = await _save_newsletter(db, user, newsletter, batch_id=batch.id)

                # 7. 이메일 발송 및 결과 반영
                deliver_result = await _deliver_newsletter(user, newsletter)
                if deliver_result.get("success", True):
                    nl_record.delivery_status = "sent"
                    logger.info(f"  [done] {user.email}")
                else:
                    nl_record.delivery_status = "failed"
                    nl_record.error_message = deliver_result.get("error", "Unknown error")
                    logger.error(f"  [fail] {user.email} -- {nl_record.error_message}")
                await db.commit()

                # 8. ReportBatch 완료 마킹
                batch.status = "done"
                batch.finished_at = datetime.now(timezone.utc)
                batch.log_count = len(log_ids)
                batch.topic_count = len(merged_topics)
                await db.commit()

                # 9. 관심도 누적 (Gemini 추가 호출 없음)
                await _update_user_interests(db, str(user.google_id), merged_topics)

            except Exception as e:
                logger.error(f"  [error] {user.email} -- {e}")
                if batch is not None:
                    try:
                        batch.status = "failed"
                        batch.finished_at = datetime.now(timezone.utc)
                        await db.commit()
                    except Exception:
                        pass
                continue

    logger.info(f"[scheduler] {send_time} batch done")


# -- per-minute batch --

async def per_minute_batch():
    """
    Every minute: match current KST HH:MM against users' send_time.
    Replaces the fixed 08:00 / 21:00 cron jobs.
    """
    now_hhmm = datetime.now(KST).strftime("%H:%M")
    await _run_batch_for_send_time(now_hhmm)


# -- new video check (hourly) --

async def check_new_videos():
    """TODO: activate after subscriptions table is implemented."""
    logger.info(f"[scheduler] check_new_videos -- {datetime.now(timezone.utc).isoformat()}")


# -- scheduler lifecycle --

def start_scheduler():
    scheduler.add_job(
        per_minute_batch,
        CronTrigger(minute="*", timezone="Asia/Seoul"),
        id="per_minute_batch",
        replace_existing=True,
    )
    scheduler.add_job(
        check_new_videos,
        IntervalTrigger(hours=1),
        id="check_new_videos",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[scheduler] 스케줄러 시작 — 08:00 아침 배치 / 21:00 저녁 배치 (KST)")


def stop_scheduler():
    """main.py shutdown 이벤트에서 호출"""
    scheduler.shutdown()
    logger.info("[scheduler] 스케줄러 종료")
