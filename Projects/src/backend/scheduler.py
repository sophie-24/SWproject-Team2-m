import os
import json
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from dotenv import load_dotenv

from database import AsyncSessionLocal, User, BehaviorLog, Newsletter
from collector.behavior_store import get_today_logs
from collector.trigger import get_triggered_topics
from agents.orchestrator import run_pipeline
from delivery.email import send_email

load_dotenv()

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


# ── 유틸 ──────────────────────────────────────────────────────────────────────


async def _get_subscribed_channel_ids(user_id: str) -> List[str]:
    """
    사용자 구독 채널 ID 목록 조회
    TODO: DB에 subscriptions 테이블 추가 후 구현
          현재는 빈 리스트 반환
    """
    return []


def _get_profile_keywords(user: User) -> List[str]:
    """
    사용자의 interest_categories(온보딩 프로필 키워드)를 반환.
    온보딩이 완료되지 않은 경우 빈 리스트 반환.
    """
    if not user.interest_categories:
        return []
    try:
        categories = json.loads(user.interest_categories)
        return categories if isinstance(categories, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _merge_keywords(triggered: List[str], profile: List[str]) -> List[str]:
    """
    오늘 행동 로그에서 추출한 triggered 키워드와
    온보딩 프로필 키워드를 합산(순서 유지, 중복 제거).
    triggered 우선 → profile로 보완.
    최대 10개 반환.
    """
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
) -> None:
    """뉴스레터를 DB에 저장"""
    record = Newsletter(
        user_id=user.google_id,
        subject=newsletter.get("subject", ""),
        content_json=json.dumps(newsletter, ensure_ascii=False),
        delivery_type=user.delivery_type,
    )
    db.add(record)
    await db.commit()


async def _deliver_newsletter(
    user: User,
    newsletter: Dict[str, Any],
) -> None:
    """뉴스레터를 이메일로 발송"""
    send_email(
        user_email=user.email,
        newsletter=newsletter,
    )


# ── 배치 실행 (send_time 필터) ────────────────────────────────────────────────


async def _run_batch_for_send_time(send_time: str) -> None:
    """
    특정 send_time(HH:MM)에 설정된 사용자들만 배치 실행.
    daily_batch()와 동일 로직이지만 send_time 필터 적용.
    """
    print(f"[scheduler] {send_time} 배치 시작")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.send_time == send_time)
        )
        users = result.scalars().all()
        print(f"[scheduler] {send_time} 대상 {len(users)}명")

        for user in users:
            try:
                today_logs = await get_today_logs(db, user_id=str(user.google_id))

                triggered_topics = get_triggered_topics(today_logs)
                profile_keywords = _get_profile_keywords(user)

                # 오늘 로그 + 관심사 프로필 항상 합산 (fallback이 아닌 merge)
                merged_topics = _merge_keywords(triggered_topics, profile_keywords)

                if not merged_topics:
                    print(f"  [스킵] {user.email} — 주제 없음 (로그/프로필 모두 없음)")
                    continue

                if triggered_topics and profile_keywords:
                    print(f"  [합산] {user.email} — 로그 {len(triggered_topics)}개 + 프로필 {len(profile_keywords)}개 → {len(merged_topics)}개")
                elif triggered_topics:
                    print(f"  [로그] {user.email} — 오늘 로그 {len(triggered_topics)}개")
                else:
                    print(f"  [프로필] {user.email} — 관심사 프로필 {len(profile_keywords)}개")

                triggered_topics = merged_topics

                subscribed_channel_ids = await _get_subscribed_channel_ids(str(user.google_id))

                newsletter = await asyncio.to_thread(
                    run_pipeline,
                    user_id=str(user.google_id),
                    raw_keywords=triggered_topics,
                    subscribed_channel_ids=subscribed_channel_ids,
                    initial_intent=user.initial_intent,
                )
                await _save_newsletter(db, user, newsletter)
                await _deliver_newsletter(user, newsletter)
                print(f"  [완료] {user.email}")

            except Exception as e:
                print(f"  [오류] {user.email} — {e}")
                continue

    print(f"[scheduler] {send_time} 배치 완료")


async def morning_batch():
    """08:00 KST 배치 — send_time이 '08:00'인 사용자"""
    await _run_batch_for_send_time("08:00")


async def evening_batch():
    """21:00 KST 배치 — send_time이 '21:00'이거나 미설정인 기본 사용자"""
    # 기존 daily_batch와 동일하게 동작 (send_time 기본값 21:00)
    await _run_batch_for_send_time("21:00")


# ── 1시간마다 새 영상 감지 ─────────────────────────────────────────────────────

async def check_new_videos():
    """
    1시간마다 실행
    구독 채널 새 영상 감지 → 즉시 분석 및 발송
    TODO: 구독 채널 DB 테이블 구현 후 활성화
    """
    print(f"[scheduler] 새 영상 감지 — {datetime.now(timezone.utc).isoformat()}")
    pass


# ── 스케줄러 등록 ─────────────────────────────────────────────────────────────

def start_scheduler():
    """
    main.py startup 이벤트에서 호출
    아침(08:00 KST) + 저녁(21:00 KST) 이중 배치
    """
    # 아침 8시 — send_time='08:00' 사용자
    scheduler.add_job(
        morning_batch,
        CronTrigger(hour=8, minute=0, timezone="Asia/Seoul"),
        id="morning_batch",
        replace_existing=True,
    )

    # 저녁 9시 (기본) — send_time='21:00' 또는 미설정 사용자
    scheduler.add_job(
        evening_batch,
        CronTrigger(hour=21, minute=0, timezone="Asia/Seoul"),
        id="evening_batch",
        replace_existing=True,
    )

    # 1시간마다 새 영상 감지
    scheduler.add_job(
        check_new_videos,
        IntervalTrigger(hours=1),
        id="check_new_videos",
        replace_existing=True,
    )

    scheduler.start()
    print("[scheduler] 스케줄러 시작 — 08:00 아침 배치 / 21:00 저녁 배치 (KST)")


def stop_scheduler():
    """main.py shutdown 이벤트에서 호출"""
    scheduler.shutdown()
    print("[scheduler] 스케줄러 종료")
