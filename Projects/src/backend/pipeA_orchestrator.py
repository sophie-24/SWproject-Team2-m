"""
pipeA_orchestrator.py — Pipeline A: 검색 키워드 → 영상 선정 → 분석 → 대시보드 반환

흐름:
  [AI 1] selector_ai  → 영상 후보 선정 (top 5)
  [AI 2] analyzer_ai  → 배치 분석 + 교차분석
  [inline]            → intent_type 파생 → category/layout 매핑 → 대시보드 조립
"""

import asyncio
from typing import List, Dict, Any

from agents.selector_ai import select_top_videos
from agents.analyzer_ai import analyze_videos
from agents.intent_ai import classify_intent

from logger import get_logger
logger = get_logger(__name__)


# intent_type → (category, layout) 매핑
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
) -> Dict[str, Any]:
    """analyzer_ai 결과 + intent 정보로 대시보드 딕셔너리 조립."""
    cat_map = _INTENT_TO_CATEGORY.get(intent_type, _DEFAULT_CATEGORY)
    summary_lines: List[str] = analyzer_result.get("summary", [])

    recommended_videos = [
        {
            "video_id":          v.get("video_id", ""),
            "title":             v.get("title", ""),
            "channel_title":     v.get("channel_title", ""),
            "thumbnail":         v.get("thumbnail",
                                      f"https://img.youtube.com/vi/{v.get('video_id','')}/mqdefault.jpg"),
            "url":               f"https://youtube.com/watch?v={v.get('video_id','')}",
            "credibility_score": v.get("credibility_score", 0.5),
            "ad_detected":       v.get("ad_detected", False),
            "summary":           v.get("summary", ""),
        }
        for v in analyzer_result.get("videos", [])
        if not v.get("ad_detected", False)
    ] or [
        {
            "video_id":          v.get("video_id", ""),
            "title":             v.get("title", ""),
            "channel_title":     v.get("channel_title", ""),
            "thumbnail":         v.get("thumbnail",
                                      f"https://img.youtube.com/vi/{v.get('video_id','')}/mqdefault.jpg"),
            "url":               f"https://youtube.com/watch?v={v.get('video_id','')}",
            "credibility_score": v.get("credibility_score", 0.5),
            "ad_detected":       False,
            "summary":           v.get("summary", ""),
        }
        for v in analyzer_result.get("videos", [])
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
) -> Dict[str, Any]:
    """
    검색 키워드를 받아 Pipeline A 전체를 실행하고 대시보드 데이터를 반환.

    Args:
        keyword:                유튜브 검색 키워드
        subscribed_channel_ids: 사용자 구독 채널 ID 목록 (없으면 빈 리스트)

    Returns:
        {
            "keyword", "category", "layout", "intent_type",
            "summary_lines", "common_conclusion",
            "controversies", "recommended_videos", "common_facts",
            "pros", "cons", "sources"
        }

    Raises:
        ValueError: 영상을 찾을 수 없는 경우
    """
    if subscribed_channel_ids is None:
        subscribed_channel_ids = []

    # Step 1: 영상 후보 선정 (sync → thread)
    logger.info(f"[pipeA] Step 1 — 영상 선정: '{keyword}'")
    videos = await asyncio.to_thread(
        select_top_videos,
        keyword=keyword,
        subscribed_channel_ids=subscribed_channel_ids,
    )
    if not videos:
        raise ValueError(f"'{keyword}' 검색 결과 영상 없음")

    # Step 2: 의도 분류 + 영상 분석 병렬 실행
    logger.info(f"[pipeA] Step 2 — 의도 분류 + 영상 분석 병렬 ({len(videos)}개)")
    intent_result, analyzer_result = await asyncio.gather(
        classify_intent([keyword], []),
        analyze_videos(keyword, videos),
    )

    intent_type = intent_result.get("intent_type", "지식형")
    logger.info(f"[pipeA] 완료 — 의도={intent_type}, 공통사실={len(analyzer_result.get('common_facts',[]))}개")

    # Step 3: 대시보드 조립 (인라인, Gemini 추가 호출 없음)
    return _build_dashboard(keyword, analyzer_result, intent_type)


# 하위 호환 alias — 기존 코드가 run_pipeline으로 호출하는 경우 대응
run_pipeline = run_pipeline_a
