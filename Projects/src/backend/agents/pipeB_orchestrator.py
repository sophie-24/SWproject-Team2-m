# Pipeline B 총괄 오케스트레이터 — intent→cluster→select→analyze→newsletter 순차 실행
import asyncio
from typing import List, Dict, Any, Optional

from agents.intent_ai import classify_intent
from agents.format_ai import decide_format
from agents.cluster_ai import cluster_topics
from agents.selector_ai import select_top_videos
from agents.analyzer_ai import analyze_videos
from agents.newsletter_ai import generate_newsletter

from logger import get_logger
logger = get_logger(__name__)


def _dashboard_to_analysis(topic: str, cached: Dict[str, Any]) -> Dict[str, Any]:
    """Pipeline A dashboard 캐시 → Pipeline B analyze_videos 반환 포맷 변환.

    Pipeline A가 이미 계산한 summary_lines / common_facts / controversies를
    재활용해 Gemini 추가 호출 없이 newsletter_ai에 전달 가능한 형식으로 변환.

    pros/cons는 Pipeline A 캐시에 없으므로 빈 리스트로 처리.
    newsletter_ai는 pros/cons 없이도 동작하며, summary/controversies로 충분한 콘텐츠 생성 가능.
    """
    rec_videos = cached.get("recommended_videos", [])
    sources = [
        {
            "title": v.get("title", ""),
            "url": (
                v.get("url")
                or (f"https://youtube.com/watch?v={v['video_id']}" if v.get("video_id") else "")
            ),
        }
        for v in rec_videos
    ]
    return {
        "keyword":       topic,
        "videos":        rec_videos,
        "common_facts":  cached.get("common_facts", []),
        "controversies": cached.get("controversies", []),
        "summary":       cached.get("summary_lines", []),
        "pros":          [],   # Pipeline A 캐시에 없음 — newsletter_ai가 빈 값 허용
        "cons":          [],
        "sources":       sources,
    }



async def run_pipeline(
    user_id: str,
    raw_keywords: List[str],
    subscribed_channel_ids: List[str] = None,
    clicked_video_titles: List[str] = None,
    initial_intent: Optional[str] = None,
    pipeline_a_cache: Optional[Dict[str, Any]] = None,
    today_logs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    오늘 수집된 키워드를 받아 전체 AI 파이프라인 실행 후 뉴스레터 데이터 반환.

    모든 Gemini 호출이 async로 처리되므로 여러 사용자가 동시에 파이프라인을
    실행해도 이벤트 루프를 블로킹하지 않는다.
    각 await 시점에 다른 코루틴으로 양보가 일어나 동시 처리가 가능하다.

    Args:
        user_id:                  사용자 ID (google_id)
        raw_keywords:             오늘 수집된 검색어/영상 제목 전체
        subscribed_channel_ids:   사용자 구독 채널 ID 목록
        clicked_video_titles:     오늘 클릭/시청한 영상 제목 목록 (intent 판단용)
        initial_intent:           온보딩 설정 초기 의도 — 로그 부족 시 intent_ai 폴백으로 사용
        today_logs:               behavior_store.get_today_logs() 반환값 (시간 메타데이터용)
                                  전달 시 cluster_ai가 시간 흐름 컨텍스트를 활용해 클러스터링

    Returns:
        generate_newsletter() 반환값
        {
            "subject", "intent_type",
            "topics": [{"topic", "summary", "pros", "cons", "sources"}]
        }

    Raises:
        ValueError: 클러스터링 결과가 없거나 분석 가능한 주제가 없는 경우
    """
    if subscribed_channel_ids is None:
        subscribed_channel_ids = []
    if clicked_video_titles is None:
        clicked_video_titles = []
    if pipeline_a_cache is None:
        # shared_cache에서 자동 로드 — 별도로 전달하지 않아도 동작
        try:
            from shared_cache import search_analysis_cache
            pipeline_a_cache = search_analysis_cache
        except ImportError:
            pipeline_a_cache = {}

    # ── Step 0: 의도 분류 (format_style 포함) ─────────────────────────────────
    logger.info("[orchestrator] Step 0 — 의도 분류")
    intent_result = await classify_intent(raw_keywords, clicked_video_titles)

    intent_type = intent_result.get("intent_type") or initial_intent or "지식형"
    format_style = intent_result["format_style"]
    logger.info(f"[orchestrator] 의도={intent_type} / 길이={format_style['length']}")

    # ── Step 1: 주제 클러스터링 ────────────────────────────────────────────────
    logger.info(f"[orchestrator] Step 1 — 주제 클러스터링 ({len(raw_keywords)}개 키워드)")
    clusters = await cluster_topics(raw_keywords, today_logs=today_logs)
    if not clusters:
        raise ValueError("클러스터링 결과 없음 — 키워드 부족")

    logger.info(f"[orchestrator] 클러스터 {len(clusters)}개 생성됨")

    # ── Step 2, 3: 주제별 순차 처리 ──────
