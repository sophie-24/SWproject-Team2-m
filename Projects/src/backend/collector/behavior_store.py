# backend/collector/behavior_store.py
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from database import BehaviorLog


async def save_behavior(
    db: AsyncSession,
    user_id: str,
    event_type: str,       # "search" | "watch"
    keyword: str,
    video_id: str = None,
) -> dict:
    """
    INPUT:
      - user_id    (str)
      - event_type ("search" | "watch")
      - keyword    (str)
      - video_id   (str, optional)

    OUTPUT:
      - saved (bool)
      - count (int) — 오늘 같은 키워드 몇 번째인지
    """
    # 로그 저장
    log = BehaviorLog(
        user_id=user_id,
        event_type=event_type,
        keyword=keyword,
        video_id=video_id,
    )
    db.add(log)
    await db.commit()

    # 오늘 같은 키워드 횟수 카운트
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    result = await db.execute(
        select(func.count())
        .where(BehaviorLog.user_id == user_id)
        .where(BehaviorLog.keyword == keyword)
        .where(BehaviorLog.logged_at >= today_start)
    )
    count = result.scalar()

    return {"saved": True, "count": count}


async def get_today_logs(db: AsyncSession, user_id: str) -> list[dict]:
    """
    오늘 해당 유저의 행동 로그 전체 조회
    → trigger.py에서 사용
    """
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    result = await db.execute(
        select(BehaviorLog)
        .where(BehaviorLog.user_id == user_id)
        .where(BehaviorLog.logged_at >= today_start)
        .order_by(BehaviorLog.logged_at)
    )
    logs = result.scalars().all()

    return [
        {
            "event_type": log.event_type,
            "keyword":    log.keyword,
            "video_id":   log.video_id,
            "logged_at":  log.logged_at.isoformat(),
        }
        for log in logs
    ]