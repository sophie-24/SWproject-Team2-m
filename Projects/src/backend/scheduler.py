# backend/scheduler.py
"""
배치 스케줄러

매일 저녁 9시:
  1. 모든 사용자 오늘 행동 로그 조회
  2. 주제 트리거 판단 (2회 이상)
  3. 주제별 멀티 에이전트 파이프라인 실행
  4. 뉴스레터 생성 및 발송
  5. 로그 초기화

1시간마다 (구독 유튜버 새 영상 감지):
  1. YouTube Data API로 구독 채널 최신 영상 확인
  2. 새 영상 발견 시 즉시 분석 → 발송
"""

import os
import json
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from dotenv import load_dotenv

from database import AsyncSessionLocal, User, BehaviorLog, Newsletter
from collector.behavior_store import get_today_logs
from collector.trigger import get_triggered_topics
from agents.orchestrator import run_pipeline
from delivery.kakao import send_kakao
from delivery.email import send_email

load_dotenv()

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


# ── 유틸 ──────────────────────────────────────────────────────────────────────

async def _get_all_users(db) -> List[User]:
    """DB에서 모든 사용자 조회"""
    result = await db.execute(select(User))
    return result.scalars().all()


async def _get_subscribed_channel_ids(user_id: str) -> List[str]:
    """
    사용자 구독 채널 ID 목록 조회
    TODO: DB에 subscriptions 테이블 추가 후 구현
          현재는 빈 리스트 반환
    """
    return []


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
    """뉴스레터를 사용자 설정에 따라 카카오 또는 이메일로 발송"""
    if user.delivery_type == "kakao" and user.kakao_uuid:
        send_kakao(
            kakao_uuid=user.kakao_uuid,
            newsletter=newsletter,
        )
    else:
        send_email(
            user_email=user.email,
            newsletter=newsletter,
        )


# ── 저녁 9시 배치 ─────────────────────────────────────────────────────────────

async def daily_batch():
    """
    매일 저녁 9시 실행
    모든 사용자의 오늘 행동 로그를 분석해 뉴스레터 발송
    """
    print(f"[scheduler] 배치 시작 — {datetime.now(timezone.utc).isoformat()}")

    async with AsyncSessionLocal() as db:
        users = await _get_all_users(db)
        print(f"[scheduler] 대상 사용자 {len(users)}명")

        for user in users:
            try:
                # 1. 오늘 행동 로그 조회
                today_logs = await get_today_logs(db, user_id=str(user.google_id))
                if not today_logs:
                    print(f"  [스킵] {user.email} — 오늘 로그 없음")
                    continue

                # 2. 트리거된 주제 추출 (2회 이상)
                triggered_topics = get_triggered_topics(today_logs)
                if not triggered_topics:
                    print(f"  [스킵] {user.email} — 트리거된 주제 없음")
                    continue

                print(f"  [처리] {user.email} — 주제 {len(triggered_topics)}개: {triggered_topics}")

                # 3. 구독 채널 조회
                subscribed_channel_ids = await _get_subscribed_channel_ids(str(user.google_id))

                # 4. 파이프라인 실행 (sync → 이벤트 루프 블로킹 방지)
                newsletter = await asyncio.to_thread(
                    run_pipeline,
                    user_id=str(user.google_id),
                    raw_keywords=triggered_topics,
                    subscribed_channel_ids=subscribed_channel_ids,
                    delivery_type=user.delivery_type,
                )

                # 5. 뉴스레터 DB 저장
                await _save_newsletter(db, user, newsletter)

                # 6. 뉴스레터 발송
                await _deliver_newsletter(user, newsletter)
                print(f"  [완료] {user.email} — 발송 성공")

            except Exception as e:
                print(f"  [오류] {user.email} — {e}")
                continue

    print(f"[scheduler] 배치 완료 — {datetime.now(timezone.utc).isoformat()}")


# ── 1시간마다 새 영상 감지 ─────────────────────────────────────────────────────

async def check_new_videos():
    """
    1시간마다 실행
    구독 채널 새 영상 감지 → 즉시 분석 및 발송
    TODO: 구독 채널 DB 테이블 구현 후 활성화
    """
    print(f"[scheduler] 새 영상 감지 — {datetime.now(timezone.utc).isoformat()}")
    # TODO: 세션 11에서 구현
    pass


# ── 스케줄러 등록 ─────────────────────────────────────────────────────────────

def start_scheduler():
    """
    main.py startup 이벤트에서 호출
    """
    # 매일 저녁 9시 (한국 시간)
    scheduler.add_job(
        daily_batch,
        CronTrigger(hour=21, minute=0, timezone="Asia/Seoul"),
        id="daily_batch",
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
    print("[scheduler] 스케줄러 시작 — 매일 21:00 KST 배치 실행")


def stop_scheduler():
    """main.py shutdown 이벤트에서 호출"""
    scheduler.shutdown()
    print("[scheduler] 스케줄러 종료")