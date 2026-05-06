"""
pipeA_orchestrator.py — Pipeline A: 검색 키워드 → 영상 선정 → 분석 → 대시보드 반환

흐름:
  [AI 1] selector_ai  → 영상 후보 선정 (top 5)          ┐ 병렬
  [AI 2] intent_ai    → 검색 의도 분류                   ┘
  [AI 3] analyzer_ai  → 배치 분석 + 의도 반영 교차분석
  [inline]            → category/layout 매핑 → 대시보드 조립

공통 응답 스키마 (Pipeline A/B 모두 준수):
  VideoItem       — 영상 카드 하나의 공통 필드
  AnalysisResult  — analyzer_ai.analyze_videos 반환 타입
  DashboardResult — run_pipeline_a 최종 반환 타입 (프론트 전달용)
"""

import asyncio
from typing import List, Dict, Any, Optional
try:
    from typing import TypedDict
except ImportError:                  # Python 3.7 호환
    from typing_extensions import TypedDict

from agents.selector_ai import select_top_videos
from agents.analyzer_ai import analyze_videos
from agents.intent_ai import classify_intent

from logger import get_logger
logger = get_logger(__name__)


# ── 공통 응답 스키마 (Pipeline A/B 공유) ─────────────────────────────────────

class VideoItem(TypedDict, total=False):
    """영상 카드 하나의 표준 필드 — selector_ai / analyzer_ai / dashboard 공통."""
    video_id:          str
    title:             str
    channel_title:     str
    thumbnail:         str    # mqdefault.jpg URL
    url:               str    # youtube.com/watch?v=…
    credibility_score: float  # 0.0 ~ 1.0
    ad_detected:       bool
    summary:           str    # 개별 영상 요약 (1~2문장)


class AnalysisResult(TypedDict, total=False):
    """
    analyzer_ai.analyze_videos 반환 타입.
    Pipeline A (실시간 검색) / Pipeline B (뉴스레터 배치) 공통으로 사용.
    """
    keyword:       str
    videos:        List[VideoItem]  # 배치 분석된 영상 목록
    common_facts:  List[str]        # 공통 사실 (3개 이상 영상 공통 언급)
    controversies: List[str]        # 쟁점 (영상 간 의견 차이)
    summary:       List[str]        # 핵심 요약 3줄
    pros:          List[str]        # 장점 (구매형·지식형)
    cons:          List[str]        # 단점 (구매형·지식형)
    sources:       List[Dict]       # [{title, url, channel_title, thumbnail_url}]


class DashboardResult(TypedDict, total=False):
    """
    run_pipeline_a 최종 반환 타입 — 프론트(side_panel / search_dashboard)에 전달.
    layout 값에 따라 프론트가 렌더링 분기:
      summary_focus  → 지식형: 핵심 요약 + 공통사실/쟁점
      card_highlight → 유희형: 영상 카드 바로 노출
      comparison     → 구매형: 장단점 비교 패널
    """
    keyword:            str
    category:           str          # "정보탐색형" | "유희탐색형" | "구매탐색형"
    layout:             str          # "summary_focus" | "card_highlight" | "comparison"
    intent_type:        str          # "지식형" | "유희형" | "구매형"
    summary_lines:      List[str]    # 핵심 요약 3줄
    common_conclusion:  str          # summary_lines[-1] 단축키
    controversies:      List[str]
    recommended_videos: List[VideoItem]
    common_facts:       List[str]
    pros:               List[str]
    cons:               List[str]
    sources:            List[Dict]


# ── intent_type → (category, layout) 매핑 ────────────────────────────────────

_INTENT_TO_CATEGORY: Dict[str, Dict[str, str]] = {
    "유희형": {"category": "유희탐색형", "layout": "card_highlight"},
    "지식형": {"category": "정보탐색형", "layout": "summary_focus"},
    "구매형": {"category": "구매탐색형", "layout": "comparison"},
}
_DEFAULT_CATEGORY = {"category": "정보탐색형", "layout": "summary_focus"}


def _build_dashboard(
    keyword: str,
    analyzer_result: Dict[str, Any],
    intent_type: str,
) -> DashboardResult:
    """analyzer_ai 결과 + intent 정보로 대시보드 딕셔너리 조립."""
    cat_map = _INTENT_TO_CATEGORY.get(intent_type, _DEFAULT_CATEGORY)
    summary_lines: List[str] = analyzer_result.get("summary", [])

    # 광고 영상 제외 → 없으면 전체 포함
    clean_videos = [v for v in analyzer_result.get("videos", []) if not v.get("ad_detected", False)]
    source_videos = clean_videos or analyzer_result.get("videos", [])

    recommended_videos: List[VideoItem] = [
        {
            "video_id":          v.get("video_id", ""),
            "title":             v.get("title", ""),
            "channel_title":     v.get("channel_title", ""),
            "thumbnail":         v.get("thumbnail",
                                      f"https://img.youtube.com/vi/{v.get('video_id', '')}/mqdefault.jpg"),
            "url":               f"https://youtube.com/watch?v={v.get('video_id', '')}",
            "credibility_score": v.get("credibility_score", 0.5),
            "ad_detected":       v.get("ad_detected", False),
            "summary":           v.get("summary", ""),
        }
        for v in source_videos
    ]

    return {
        "keyword":            keyword,
        "category":           cat_map["category"],
        "layout":             cat_map["layout"],
        "intent_type":        intent_type,
        "summary_lines":      summary_lines,
        "common_conclusion":  summary_lines[-1] if summary_lines else "",
        "controversies":      analyzer_result.get("controversies", []),
        "recommended_videos": recommended_videos,
        "common_facts":       analyzer_result.get("common_facts", []),
        "pros":               analyzer_result.get("pros", []),
        "cons":               analyzer_result.get("cons", []),
        "sources":            analyzer_result.get("sources", []),
    }


async def run_pipeline_a(
    keyword: str,
    subscribed_channel_ids: List[str] = None,
    user_categories: List[str] = None,
    clicked_channel_ids: List[str] = None,
) -> DashboardResult:
    """
    검색 키워드를 받아 Pipeline A 전체를 실행하고 대시보드 데이터를 반환.

    실행 순서:
      Step 1: 영상 선정 + 의도 분류 병렬 실행 (서로 독립적)
      Step 2: 의도 확정 후 → 영상 분석 (intent_type + format_style 전달)
      Step 3: Final Score = pre_score × credibility_score 계산 후 재정렬
      Step 4: 대시보드 조립

    Args:
        keyword:                유튜브 검색 키워드
        subscribed_channel_ids: 사용자 구독 채널 ID 목록 (ω₂)
        user_categories:        사용자 관심사 카테고리 목록 (ω₃ 조건 매칭)
        clicked_channel_ids:    이전에 시청한 채널 ID 목록 (ω₄ 클릭 여부)

    Returns:
        DashboardResult 딕셔너리

    Raises:
        ValueError: 영상을 찾을 수 없는 경우
    """
    if subscribed_channel_ids is None:
        subscribed_channel_ids = []
    if user_categories is None:
        user_categories = []
    if clicked_channel_ids is None:
        clicked_channel_ids = []

    # Step 1: 영상 선정 + 의도 분류 병렬 (두 작업은 서로 독립적)
    logger.info(f"[pipeA] Step 1 — 영상 선정 + 의도 분류 병렬: '{keyword}'")
    (videos, intent_result) = await asyncio.gather(
        asyncio.to_thread(
            select_top_videos,
            keyword,
            subscribed_channel_ids,
            user_categories,
            clicked_channel_ids,
        ),
        classify_intent([keyword], []),
    )

    if not videos:
        raise ValueError(f"'{keyword}' 검색 결과 영상 없음")

    intent_type  = intent_result.get("intent_type", "지식형")
    format_style = intent_result.get("format_style")
    logger.info(f"[pipeA] 의도 확정: {intent_type} — 영상 {len(videos)}개 분석 시작")

    # pre_score 맵 (video_id → pre_score) — selector_ai 반환값 보존
    pre_score_map: Dict[str, float] = {v["video_id"]: v.get("score", 0.0) for v in videos}

    # Step 2: 영상 분석 — 의도(intent_type)와 포맷 스타일을 전달해 맞춤 교차분석
    analyzer_result = await analyze_videos(
        keyword=keyword,
        videos=videos,
        format_style=format_style,
        intent_type=intent_type,
    )

    # Step 3: Final Score = pre_score × credibility_score, 재정렬
    for v in analyzer_result.get("videos", []):
        pre  = pre_score_map.get(v["video_id"], 0.0)
        cred = v.get("credibility_score", 0.5)
        v["final_score"] = round(pre * cred, 6)
    analyzer_result["videos"].sort(key=lambda x: x.get("final_score", 0.0), reverse=True)

    logger.info(
        f"[pipeA] 완료 — 의도={intent_type}, "
        f"공통사실={len(analyzer_result.get('common_facts', []))}개"
    )

    # Step 4: 대시보드 조립 (인라인, Gemini 추가 호출 없음)
    return _build_dashboard(keyword, analyzer_result, intent_type)


# 하위 호환 alias — 기존 코드가 run_pipeline으로 호출하는 경우 대응
run_pipeline = run_pipeline_a
