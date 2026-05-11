# APScheduler 기반 Pipeline B 배치 실행기 — 사용자별 send_time에 뉴스레터 생성·발송
import os
import json
import uuid
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo
from sqlalchemy import or_
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import date as date_type
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from dotenv import load_dotenv

from database import AsyncSessionLocal, User, BehaviorLog, Newsletter, ReportBatch, UserInterest
from behavior_store import get_today_logs
from trigger import get_triggered_topics
from agents.pipeB_orchestrator import run_pipeline
from mailer import send_email

load_dotenv()
from logger import get_logger
logger = get_logger(__name__)

KST = ZoneInfo("Asia/Seoul")
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


# -- util --


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
    """뉴스레터를 DB에 저장하고 ORM 객체를 반환. delivery_status는 'generated'로 시작."""
    record = Newsletter(
        user_id=user.google_id,
        subject=newsletter.get("subject", ""),
        content_json=json.dumps(newsletter, ensure_ascii=False),
        delivery_status="generated",
        batch_id=batch_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def _deliver_newsletter(
    user: User, newsletter: Dict[str, Any], newsletter_type: str = "interest"
) -> Dict[str, Any]:
    """이메일 발송 후 결과 딕셔너리 반환. {"success": bool, "error": str(optional)}"""
    try:
        result = send_email(user_email=user.email, newsletter=newsletter, newsletter_type=newsletter_type)
        if result is None:
            return {"success": True}
        return result
    except Exception as e:
        logger.error(f"[deliver] 예외 발생: {e}")
        return {"success": False, "error": str(e)}


async def _update_user_interests(db, user_id: str, topics: List[str]) -> None:
    """Pipeline B 실행 후 cluster_ai 결과 토픽으로 user_interests weight 누적.
    이미 존재하는 카테고리면 weight+1 + last_seen_at 갱신, 없으면 weight=1로 신규 생성.
    Gemini 추가 호출 없음 -- merged_topics 재활용.
    2차 설계: source='behavior', last_seen_at 기록 추가.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for topic in topics:
        stmt = (
            pg_insert(UserInterest)
            .values(
                user_id=user_id,
                category=topic,
                weight=1,
                source="behavior",
                last_seen_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_user_interest_category",
                set_={
                    "weight": UserInterest.weight + 1,
                    "last_seen_at": now,
                    "updated_at": now,
                },
            )
        )
        await db.execute(stmt)
    await db.commit()


# ── 뉴스레터 생성 우선순위 fallback ─────────────────────────────────────────────

async def _get_fallback_topics(db, user: "User", today_logs: List[Dict]) -> List[str]:
    """오늘 pending 로그의 distinct keyword 수를 기준으로 토픽 소스를 결정.
    1순위: distinct keyword >= 2 → trigger.py 결과 반환 (오늘 로그 기반)
    2순위: distinct keyword < 2 → user_interests 상위 토픽으로 보완
    3순위: user_interests 없으면 → users.interest_categories (온보딩 관심사) 사용
    """
    # 1순위: 오늘 distinct keyword 수 확인
    distinct_keywords = {
        log.get("keyword", "").strip().lower()
        for log in today_logs
        if log.get("keyword")
    } - {""}
    MIN_DISTINCT = 2

    if len(distinct_keywords) >= MIN_DISTINCT:
        return []  # 오늘 로그 충분 → 호출부에서 triggered_topics를 그대로 사용

    # 2순위: user_interests 상위 토픽으로 보완
    interest_result = await db.execute(
        select(UserInterest.category)
        .where(UserInterest.user_id == str(user.google_id))
        .order_by(UserInterest.weight.desc())
        .limit(10)
    )
    interest_topics = [row[0] for row in interest_result.all()]
    if interest_topics:
        logger.info(f"  [fallback] {user.email} — user_interests 사용 ({len(interest_topics)}개)")
        return interest_topics

    # 3순위: 온보딩 관심사 (interest_categories)
    onboarding_topics = _get_profile_keywords(user)
    if onboarding_topics:
        logger.info(f"  [fallback] {user.email} — interest_categories 사용 ({len(onboarding_topics)}개)")
        return onboarding_topics

    return []


# -- duplicate send guard --

async def _already_sent_in_window(db, user_id: str, hours: int = 10) -> bool:
    """최근 N시간 이내에 발송된 뉴스레터가 있으면 True (오전/오후 슬롯 중복 방지)"""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    result = await db.execute(
        select(Newsletter).where(
            Newsletter.user_id == user_id,
            Newsletter.delivered_at >= cutoff,
        )
    )
    return result.scalar_one_or_none() is not None


# -- batch --

def _parse_send_times(raw: str) -> List[str]:
    """send_time JSON 배열 문자열 → HH:MM 리스트. 파싱 실패 시 ["21:00"] 반환."""
    try:
        times = json.loads(raw or '["21:00"]')
        return times if isinstance(times, list) else ["21:00"]
    except (json.JSONDecodeError, TypeError):
        return ["21:00"]


async def _run_batch_for_send_time(send_time: str) -> None:
    logger.info(f"[scheduler] {send_time} batch start")

    async with AsyncSessionLocal() as db:
        if send_time == "21:00":
            time_filter = or_(
                User.send_time == send_time,
                User.send_time == None,  # noqa: E711
            )
        else:
            time_filter = (User.send_time == send_time)

        result = await db.execute(
            select(User).where(User.is_subscribed == True)  # noqa: E712
        )
        all_users = result.scalars().all()

        # send_time JSON 배열에 현재 시각이 포함된 유저만 추출
        users = [u for u in all_users if send_time in _parse_send_times(u.send_time)]
        logger.info(f"[scheduler] {send_time} -> {len(users)} users")

        for user in users:
            batch: Optional[ReportBatch] = None
            try:
                if await _already_sent_in_window(db, str(user.google_id), hours=10):
                    logger.warning(f"  [skip] {user.email} already sent today")
                    continue

                now = datetime.now(timezone.utc).replace(tzinfo=None)

                # 1. ReportBatch 생성 (status='created') — window_type / period_start / period_end 기록
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                # send_time 배열 중 가장 이른 시각이고 2회 이상 발송 설정이면 before_cutoff
                user_times = sorted(_parse_send_times(user.send_time))
                window_type = (
                    "before_cutoff" if len(user_times) > 1 and send_time == user_times[0]
                    else "after_cutoff"
                )
                batch = ReportBatch(
                    user_id=str(user.google_id),
                    window_type=window_type,
                    period_start=today_start,
                    period_end=now,
                )
                db.add(batch)
                await db.commit()
                await db.refresh(batch)

                # 파이프라인 진입 전 processing 상태로 전환
                batch.status = "processing"
                await db.commit()

                # 2. 오늘의 pending 로그 ID 수집
                log_id_result = await db.execute(
                    select(BehaviorLog.id).where(
                        BehaviorLog.user_id == str(user.google_id),
                        BehaviorLog.logged_at >= today_start,
                        BehaviorLog.status == "pending",
                    )
                )
                log_ids = [row[0] for row in log_id_result.all()]

                # 3. 트리거 분석 + 우선순위 fallback
                today_logs = await get_today_logs(db, user_id=str(user.google_id))
                triggered_topics = get_triggered_topics(today_logs)

                fallback = await _get_fallback_topics(db, user, today_logs)
                if fallback:
                    # 2·3순위: user_interests 또는 interest_categories 보완
                    merged_topics = _merge_keywords(fallback, [])
                else:
                    # 1순위: 오늘 로그 충분 → trigger 결과 + 프로필 병합
                    profile_keywords = _get_profile_keywords(user)
                    merged_topics = _merge_keywords(triggered_topics, profile_keywords)

                if not merged_topics:
                    logger.warning(f"  [skip] {user.email} no topics")
                    batch.status = "failed"
                    batch.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await db.commit()
                    continue


                # 4. 사용한 로그를 processed 로 마킹 — 2차 설계: processed_at 기록
                if log_ids:
                    await db.execute(
                        update(BehaviorLog)
                        .where(BehaviorLog.id.in_(log_ids))
                        .values(
                            status="processed",
                            batch_id=batch.id,
                            processed_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        )
                    )
                    await db.commit()

                # 5. 파이프라인 실행 — 구독 채널 ID DB 캐시 로드 (selector_ai 가산점용)
                try:
                    sub_ch = json.loads(user.subscribed_channels or "[]")
                    sub_ch = sub_ch if isinstance(sub_ch, list) else []
                except Exception:
                    sub_ch = []

                newsletter = await run_pipeline(
                    user_id=str(user.google_id),
                    raw_keywords=triggered_topics,
                    subscribed_channel_ids=sub_ch,
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
                batch.status = "completed"
                batch.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                batch.topic_count = len(merged_topics)
                await db.commit()

                # 9. 관심도 누적 — 2차 설계: source='behavior', last_seen_at 기록
                await _update_user_interests(db, str(user.google_id), merged_topics)

            except Exception as e:
                logger.error(f"  [error] {user.email} -- {e}")
                if batch is not None:
                    try:
                        batch.status = "failed"
                        batch.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
