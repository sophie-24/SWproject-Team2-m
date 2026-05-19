# 영상 선정 에이전트 — YouTube API 후보 수집 후 ViewRate × 개인화(키워드·구독·조건매칭·클릭·최신성) 공식으로 상위 5개 선정
"""
selector_ai.py — 영상 선별 및 스코어링 (Feature 03)

PPT 스코어링 공식:
  Final Score = ViewRate × 신뢰도 × 개인화 적합도

  ViewRate       = 조회수 / 업로드 후 경과 시간(시간 단위)  → 정규화 후 사용
  신뢰도         = ω₁(자막품질) + ω₂(1-광고확률) + ω₃(채널신뢰도) + ω₄(정보일관성)
                  → analyzer_ai 단계에서 credibility_score로 반영 후 orchestrator에서 곱셈
  개인화 적합도  = ω₁·키워드유사도 + ω₂·구독여부 + ω₃·조건매칭 + ω₄·클릭여부 + ω₅·최신성
                  ω₁=0.40, ω₂=0.20, ω₃=0.15, ω₄=0.10, ω₅=0.15

  여기서는 analyzer_ai 이전 단계이므로:
    pre_score = norm_view_rate × personalization_score
  최종 신뢰도 곱셈은 pipeA_orchestrator에서 credibility_score 반영 후 처리.
"""
import os
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

from youtube_search import search_videos, _get_api_client

load_dotenv()
from logger import get_logger
logger = get_logger(__name__)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# ── 개인화 가중치 (PPT Feature 03 — 5개 컴포넌트) ───────────────────────────
W_KEYWORD    = 0.40  # ω₁ 키워드 유사도   (제목 내 검색어 포함 비율)
W_SUBSCRIBED = 0.20  # ω₂ 구독 채널 여부  (구독 채널이면 1.0, 아니면 0.0)
W_CONDITION  = 0.15  # ω₃ 조건 매칭       (유저 관심사 카테고리와 영상 주제 일치)
W_CLICK      = 0.10  # ω₄ 클릭 여부       (유저가 이전에 시청한 채널이면 1.0)
W_RECENCY    = 0.15  # ω₅ 최신성          (업로드 시점 기준 선형 감소)


def _parse_duration_seconds(iso_duration: str) -> int:
    """ISO 8601 duration (e.g. PT1M30S) → 초 단위 정수"""
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        iso_duration or "",
    )
    if not match:
        return 0
    hours   = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _hours_since_upload(published_at: str) -> float:
    """
    업로드 후 경과 시간(시간 단위).
    계산 실패 시 720.0 반환 (30일 기본값).
    """
    try:
        pub  = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        now  = datetime.now(timezone.utc)
        diff = (now - pub).total_seconds()
        return max(diff / 3600.0, 1.0)  # 최소 1시간 (0으로 나누기 방지)
    except Exception:
        return 720.0


def _recency_score(published_at: str) -> float:
    """
    최신성 점수 (0.0 ~ 1.0).
    - 7일 이내:   1.0
    - 30일 이내:  선형 감소 (1.0 → 0.5)
    - 365일 이내: 선형 감소 (0.5 → 0.0)
    - 365일 초과: 0.0
    """
    try:
        pub      = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        now      = datetime.now(timezone.utc)
        days_old = (now - pub).days
        if days_old <= 7:
            return 1.0
        elif days_old <= 30:
            return 1.0 - 0.5 * (days_old - 7) / (30 - 7)
        elif days_old <= 365:
            return 0.5 - 0.5 * (days_old - 30) / (365 - 30)
        else:
            return 0.0
    except Exception:
        return 0.0


def _condition_match_score(title: str, user_categories: List[str]) -> float:
    """
    조건 매칭 점수 (0.0 ~ 1.0).
    유저 관심사 카테고리 키워드가 영상 제목에 얼마나 포함되는지 측정.
    """
    if not user_categories or not title:
        return 0.0
    title_lower = title.lower()
    matched = 0
    for cat in user_categories:
        tokens = [t.lower() for t in cat.split() if len(t) > 1]
        if any(t in title_lower for t in tokens):
            matched += 1
    return min(1.0, matched / max(len(user_categories), 1) * 3)  # 1/3 매칭만 돼도 1.0


def _keyword_similarity(title: str, topic: str) -> float:
    """
    제목에 검색 주제 토큰이 얼마나 포함되었는지 (0.0 ~ 1.0).
    단순 토큰 매칭 — 고급 임베딩 없이 빠른 계산.
    """
    if not topic or not title:
        return 0.0
    topic_tokens = [t.lower() for t in topic.split() if len(t) > 1]
    if not topic_tokens:
        return 0.0
    title_lower = title.lower()
    matched = sum(1 for t in topic_tokens if t in title_lower)
    return matched / len(topic_tokens)


def _get_subscriber_counts(channel_ids: List[str]) -> Dict[str, int]:
    """채널 ID 목록에 대한 구독자 수 일괄 조회"""
    if not channel_ids or not YOUTUBE_API_KEY:
        return {}

    youtube = _get_api_client()
    response = (
        youtube.channels()
        .list(part="statistics", id=",".join(channel_ids))
        .execute()
    )

    result = {}
    for item in response.get("items", []):
        cid   = item["id"]
        stats = item.get("statistics", {})
        result[cid] = int(stats.get("subscriberCount", 0))
    return result


def select_top_videos(
    topic: str,
    subscribed_channel_ids: List[str] = None,
    user_categories: List[str] = None,
    clicked_channel_ids: List[str] = None,
    max_fetch: int = 15,
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """
    주제로 유튜브 영상 후보를 수집하고 PPT 스코어링 공식으로 상위 top_n개 선정.

    스코어링: pre_score = norm_view_rate × personalization_score
      - norm_view_rate      : ViewRate(조회수/경과시간) 정규화
      - personalization_score:
          ω₁·keyword_sim + ω₂·subscribed + ω₃·condition_match
          + ω₄·click_history + ω₅·recency

    Args:
        topic:                  검색 주제
        subscribed_channel_ids: 사용자 구독 채널 ID 목록 (ω₂)
        user_categories:        사용자 관심사 카테고리 목록 — 조건 매칭용 (ω₃)
        clicked_channel_ids:    유저가 이전에 시청한 채널 ID 목록 — 클릭 여부용 (ω₄)
        max_fetch:              YouTube API에서 가져올 후보 영상 수 (기본 15 — 광고 필터 후 5개 확보 여유)
        top_n:                  최종 선정 영상 수 (기본 5)

    Returns:
        점수 내림차순으로 정렬된 상위 top_n개 영상 메타데이터 (subscriber_count 포함)
    """
    if subscribed_channel_ids is None:
        subscribed_channel_ids = []
    if user_categories is None:
        user_categories = []
    if clicked_channel_ids is None:
        clicked_channel_ids = []

    subscribed_set   = set(subscribed_channel_ids)
    clicked_set      = set(clicked_channel_ids)

    # 1. 후보 영상 수집
    candidates = search_videos(topic, max_results=max_fetch)

    # 2. 쇼츠 제거 (60초 이하)
    candidates = [
        v for v in candidates
        if _parse_duration_seconds(v.get("duration", "")) > 60
    ]

    # 3. 유료 광고 사전 제거 — hasPaidProductPlacement=True인 영상 제외
    # (None은 미확인으로 통과, True만 확실히 제거 → analyzer_ai 자막 수집·Gemini 토큰 절약)
    before_ad_filter = len(candidates)
    candidates = [v for v in candidates if v.get("has_paid_placement") is not True]
    removed = before_ad_filter - len(candidates)
    if removed:
        logger.info(f"[selector] 유료 광고 사전 제거: {removed}개 제외")

    # 5. 중복 제거 (video_id 기준)
    seen: set = set()
    unique_candidates = []
    for v in candidates:
        if v["video_id"] not in seen:
            seen.add(v["video_id"])
            unique_candidates.append(v)
    candidates = unique_candidates

    if not candidates:
        return []

    # 6. 구독자 수 일괄 조회 (채널 신뢰도용 — analyzer_ai에서 credibility 계산 시 사용)
    channel_ids = [v["channel_id"] for v in candidates if v.get("channel_id")]
    subscriber_counts = _get_subscriber_counts(list(set(channel_ids)))

    # 7. ViewRate = 조회수 / 업로드 후 경과 시간(시간 단위)
    raw_view_rates = []
    for v in candidates:
        view_count  = v.get("view_count", 0)
        hours_since = _hours_since_upload(v.get("published_at", ""))
        raw_view_rates.append(view_count / hours_since)

    # 8. ViewRate 정규화 (max 기준)
    max_vr = max(raw_view_rates) if raw_view_rates else 1.0
    if max_vr == 0:
        max_vr = 1.0

    # 9. 스코어 계산: pre_score = norm_view_rate × personalization
    scored = []
    for v, raw_vr in zip(candidates, raw_view_rates):
        norm_view_rate = raw_vr / max_vr

        # 개인화 적합도 — 5개 컴포넌트
        keyword_sim     = _keyword_similarity(v.get("title", ""), topic)
        is_subscribed   = 1.0 if v.get("channel_id", "") in subscribed_set else 0.0
        condition_match = _condition_match_score(v.get("title", ""), user_categories)
        click_score     = 1.0 if v.get("channel_id", "") in clicked_set else 0.0
        recency         = _recency_score(v.get("published_at", ""))

        personalization = (
            W_KEYWORD   * keyword_sim
            + W_SUBSCRIBED  * is_subscribed
            + W_CONDITION   * condition_match
            + W_CLICK       * click_score
            + W_RECENCY     * recency
        )

        # PPT 공식: pre_score = ViewRate × 개인화
        # 신뢰도(credibility)는 analyzer_ai 이후 orchestrator에서 곱셈
        pre_score = norm_view_rate * max(personalization, 0.05)

        scored.append({
            **v,
            "subscriber_count":  subscriber_counts.get(v.get("channel_id", ""), 0),
            "is_subscribed":     bool(is_subscribed),
            "keyword_sim":       round(keyword_sim, 4),
            "condition_match":   round(condition_match, 4),
            "click_score":       round(click_score, 4),
            "recency_score":     round(recency, 4),
            "personalization":   round(personalization, 4),
            "view_rate_raw":     round(raw_vr, 2),
            "score":             round(pre_score, 6),
        })

    # 10. 점수 내림차순 정렬 후 상위 top_n개 선정
    scored.sort(key=lambda x: x["score"], reverse=True)

    logger.info(
        f"[selector] '{topic}' — 후보 {len(candidates)}개 → 상위 {top_n}개 선정"
        f" (유료광고 사전제거 {removed}개, ViewRate×개인화 공식)"
    )
    return scored[:top_n]
