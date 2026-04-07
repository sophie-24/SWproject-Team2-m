import os
import re
from datetime import datetime, timezone
from typing import List, Dict, Any

from googleapiclient.discovery import build
from dotenv import load_dotenv

from youtube_search import search_videos

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# 가중치 설정
W1_VIEW_RATE = 0.5       # 조회수/구독자수 (참여도)
W2_SUBSCRIBED = 0.3      # 구독 채널 여부
W3_RECENCY = 0.2         # 최신성


def _parse_duration_seconds(iso_duration: str) -> int:
    """ISO 8601 duration (e.g. PT1M30S) → 초 단위 정수"""
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        iso_duration or "",
    )
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _get_subscriber_counts(channel_ids: List[str]) -> Dict[str, int]:
    """채널 ID 목록에 대한 구독자 수 일괄 조회"""
    if not channel_ids:
        return {}

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    response = (
        youtube.channels()
        .list(part="statistics", id=",".join(channel_ids))
        .execute()
    )

    result = {}
    for item in response.get("items", []):
        cid = item["id"]
        stats = item.get("statistics", {})
        result[cid] = int(stats.get("subscriberCount", 0))
    return result


def _recency_score(published_at: str) -> float:
    """
    발행일 기준 최신성 점수 (0.0 ~ 1.0).
    - 30일 이내: 1.0
    - 365일 이내: 선형 감소
    - 365일 초과: 0.0
    """
    try:
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days_old = (now - pub).days
        if days_old <= 30:
            return 1.0
        elif days_old <= 365:
            return 1.0 - (days_old - 30) / (365 - 30)
        else:
            return 0.0
    except Exception:
        return 0.0


def select_top_videos(
    keyword: str,
    subscribed_channel_ids: List[str] = None,
    max_fetch: int = 10,
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """
    키워드로 유튜브 영상 후보를 수집하고 점수 기반으로 상위 top_n개를 반환.

    Args:
        keyword: 검색 키워드
        subscribed_channel_ids: 사용자 구독 채널 ID 목록
        max_fetch: YouTube API에서 가져올 후보 영상 수 (기본 10)
        top_n: 최종 선정 영상 수 (기본 5)

    Returns:
        점수 내림차순으로 정렬된 상위 top_n개 영상 메타데이터 + score 필드 포함
    """
    if subscribed_channel_ids is None:
        subscribed_channel_ids = []

    subscribed_set = set(subscribed_channel_ids)

    # 1. 후보 영상 수집 (최대 max_fetch개)
    candidates = search_videos(keyword, max_results=max_fetch)

    # 2. 쇼츠 제거 (60초 이하)
    candidates = [
        v for v in candidates
        if _parse_duration_seconds(v.get("duration", "")) > 60
    ]

    # 3. 중복 제거 (video_id 기준)
    seen = set()
    unique_candidates = []
    for v in candidates:
        if v["video_id"] not in seen:
            seen.add(v["video_id"])
            unique_candidates.append(v)
    candidates = unique_candidates

    if not candidates:
        return []

    # 4. 채널별 구독자 수 조회
    channel_ids = list({v["channel_id"] for v in candidates})
    subscriber_map = _get_subscriber_counts(channel_ids)

    # 5. 점수 계산
    # view_rate = 조회수 / 구독자수 (구독자 0이면 조회수 자체를 대체값으로 사용)
    # view_rate를 0~1로 정규화하기 위해 최댓값으로 나눔
    raw_view_rates = []
    for v in candidates:
        sub_count = subscriber_map.get(v["channel_id"], 0)
        view_count = v.get("view_count", 0)
        if sub_count > 0:
            raw_view_rates.append(view_count / sub_count)
        else:
            raw_view_rates.append(float(view_count))

    max_view_rate = max(raw_view_rates) if raw_view_rates else 1.0
    if max_view_rate == 0:
        max_view_rate = 1.0

    scored = []
    for v, raw_vr in zip(candidates, raw_view_rates):
        norm_view_rate = raw_vr / max_view_rate                     # 0~1 정규화
        is_subscribed = 1.0 if v["channel_id"] in subscribed_set else 0.0
        recency = _recency_score(v.get("published_at", ""))

        score = (
            W1_VIEW_RATE * norm_view_rate
            + W2_SUBSCRIBED * is_subscribed
            + W3_RECENCY * recency
        )

        scored.append({
            **v,
            "subscriber_count": subscriber_map.get(v["channel_id"], 0),
            "is_subscribed": bool(is_subscribed),
            "recency_score": round(recency, 4),
            "score": round(score, 4),
        })

    # 6. 점수 내림차순 정렬 후 상위 top_n개 선정
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]
