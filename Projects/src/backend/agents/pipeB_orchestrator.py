# Pipeline B 총괄 오케스트레이터 — 토픽별 (intent∥select → analyze) 순차 반복 → newsletter
import asyncio
from collections import Counter
from typing import List, Dict, Any, Optional

from agents.intent_ai import classify_intent, FORMAT_MAP as INTENT_FORMAT_MAP
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
            "title":         v.get("title", ""),
            "url": (
                v.get("url")
                or (f"https://youtube.com/watch?v={v['video_id']}" if v.get("video_id") else "")
            ),
            "thumbnail_url": v.get("thumbnail_url", ""),
            "channel_title": v.get("channel_title", ""),
            "summary":       v.get("summary", ""),
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
    pipeline_a_cache: Optional[Dict[str, Any]] = None,
    skip_clustering: bool = True,  # 항상 True — cluster_ai 제거 (Issue 10)
) -> Dict[str, Any]:
    """
    하트 관심 토픽을 받아 전체 AI 파이프라인 실행 후 뉴스레터 데이터 반환.

    모든 Gemini 호출이 async로 처리되므로 여러 사용자가 동시에 파이프라인을
    실행해도 이벤트 루프를 블로킹하지 않는다.

    Args:
        user_id:                사용자 ID (google_id)
        raw_keywords:           하트 관심 토픽 목록 (이미 정제됨)
        subscribed_channel_ids: 사용자 구독 채널 ID 목록
        clicked_video_titles:   시청한 영상 제목 목록 (intent 판단 보조용)
        pipeline_a_cache:       Pipeline A 캐시 (동일 키워드 재활용용)

    Returns:
        generate_newsletter() 반환값
        {
            "subject", "intent_type",
            "topics": [{"topic", "summary", "pros", "cons", "sources"}]
        }

    Raises:
        ValueError: 분석 가능한 주제가 없는 경우
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

    # ── Step 0: 토픽 목록 구성 (cluster_ai 제거 — 하트 토픽은 이미 정제됨) ────
    clusters = [{"topic": kw, "keywords": [kw]} for kw in raw_keywords]
    logger.info(f"[orchestrator] Step 0 — {len(clusters)}개 토픽 직접 사용")

    # ── Step 1·2·3: 토픽별 순차 반복 (토픽 간 순차, 토픽 내 일부 병렬) ─────────
    # ∙ 캐시 미스: intent_ai(Gemini) + select_top_videos(YouTube API) 병렬 실행
    #              → 두 작업이 서로 독립적이므로 asyncio.gather 적용 (Pipeline A와 동일)
    # ∙ 캐시 히트: select_top_videos 불필요 → intent_ai만 단독 실행 (YouTube API 절약)
    # ∙ 토픽 간은 analyzer_ai Gemini 호출 순서 보장을 위해 순차 유지
    analyses: List[Dict[str, Any]] = []

    _default_intent = lambda: {          # noqa: E731  — 기본값 팩토리
        "intent_type": "지식형",
        "format_style": dict(INTENT_FORMAT_MAP["지식형"]),
    }

    for cluster in clusters:
        topic = cluster.get("topic", "")
        if not topic:
            continue

        # Pipeline A 캐시 확인 — 캐시 히트 여부에 따라 병렬 범위 결정
        cache_hit = pipeline_a_cache.get(topic) or pipeline_a_cache.get(f"{user_id}:{topic}")

        if cache_hit:
            # 캐시 히트: intent_ai만 실행 (영상 선정 불필요)
            logger.info(f"[orchestrator] Step 1 — '{topic}' 의도 분류 (캐시 히트)")
            try:
                intent_result = await classify_intent([topic], clicked_video_titles)
            except Exception as e:
                logger.warning(f"[orchestrator] '{topic}' 의도 분류 실패 — 기본값: {e}")
                intent_result = _default_intent()
            intent_type  = intent_result.get("intent_type") or "지식형"
            format_style = intent_result["format_style"]
            logger.info(f"[orchestrator] '{topic}' → Pipeline A 캐시 재활용 / 의도={intent_type}")
            analysis = _dashboard_to_analysis(topic, cache_hit)
            analysis["intent_type"]  = intent_type
            analysis["format_style"] = format_style
            analyses.append(analysis)
            continue

        # 캐시 미스: Step 1(intent) + Step 2(영상 선정) 병렬 실행
        logger.info(f"[orchestrator] Step 1+2 — '{topic}' 의도 분류 + 영상 선정 병렬")
        results = await asyncio.gather(
            classify_intent([topic], clicked_video_titles),
            asyncio.to_thread(select_top_videos, topic, subscribed_channel_ids),
            return_exceptions=True,
        )

        # intent 결과 처리
        if isinstance(results[0], Exception):
            logger.warning(f"[orchestrator] '{topic}' 의도 분류 실패 — 기본값: {results[0]}")
            intent_result = _default_intent()
        else:
            intent_result = results[0]
        intent_type  = intent_result.get("intent_type") or "지식형"
        format_style = intent_result["format_style"]
        logger.info(f"[orchestrator] '{topic}' 의도={intent_type} / 길이={format_style['length']}")

        # 영상 선정 결과 처리
        if isinstance(results[1], Exception):
            logger.warning(f"[orchestrator] '{topic}' 영상 선정 실패: {results[1]}")
            videos = []
        else:
            videos = results[1]

        if not videos:
            logger.warning(f"[orchestrator] '{topic}' 영상 없음 — 스킵")
            continue

        # Step 3: 영상 분석 (intent + format 확정 후 실행)
        logger.info(f"[orchestrator] Step 3 — '{topic}' 영상 {len(videos)}개 분석")
        try:
            analysis = await analyze_videos(
                keyword=topic,
                videos=videos,
                format_style=format_style,
                intent_type=intent_type,
            )
            # 토픽별 intent 정보를 analysis에 저장 → newsletter_ai에서 섹션별 포맷 적용
            analysis["intent_type"]  = intent_type
            analysis["format_style"] = format_style
            analyses.append(analysis)
        except Exception as e:
            logger.warning(f"[orchestrator] '{topic}' 분석 실패: {e}")

    if not analyses:
        raise ValueError("분석 가능한 주제 없음 — 영상 선정 실패")

    # ── Step 4: 뉴스레터 조립 ──────────────────────────────────────────────────
    # 뉴스레터 제목/전체 포맷은 dominant intent(가장 많이 나온 의도)로 결정
    intent_counts    = Counter(a.get("intent_type", "지식형") for a in analyses)
    dominant_intent  = intent_counts.most_common(1)[0][0]
    dominant_format  = next(
        (a["format_style"] for a in analyses if a.get("intent_type") == dominant_intent),
        dict(INTENT_FORMAT_MAP["지식형"]),
    )
    logger.info(
        f"[orchestrator] Step 4 — 뉴스레터 조립 ({len(analyses)}개 주제)"
        f" / dominant 의도={dominant_intent}"
    )
    newsletter = await generate_newsletter(
        user_id=user_id,
        analyses=analyses,
        format_style=dominant_format,
        intent_type=dominant_intent,
    )
    logger.info(f"[orchestrator] 완료 — subject='{newsletter.get('subject', '')}'")
    return newsletter
