# 사용자 행동 로그 DB 저장·조회 — search/watch 이벤트 수집 (Pipeline B 트리거 원천 데이터)
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

    # 오늘 같은 키워드 횟수 카운트 (KST 자정 기준)
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
    kst_midnight = datetime.now(KST).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc).replace(tzinfo=None)

    result = await db.execute(
        select(func.count())
        .where(BehaviorLog.user_id == user_id)
        .where(BehaviorLog.keyword == keyword)
        .where(BehaviorLog.logged_at >= kst_midnight)
    )
    count = result.scalar()
    return {"saved": True, "count": count}


async def get_today_logs(db: AsyncSession, user_id: str) -> list[dict]:
    """
    오늘 해당 유저의 행동 로그 전체 조회
    → trigger.py에서 사용
    """
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
    kst_midnight = datetime.now(KST).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc).replace(tzinfo=None)
    result = await db.execute(
        select(BehaviorLog)
        .where(BehaviorLog.user_id == user_id)
        .where(BehaviorLog.logged_at >= kst_midnight)
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
