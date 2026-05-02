from typing import List, Dict, Any, Optional

from agents.intent_ai import classify_intent
from agents.cluster_ai import cluster_topics
from agents.selector_ai import select_top_videos
from agents.analyzer_ai import analyze_videos
from agents.newsletter_ai import generate_newsletter


def run_pipeline(
    user_id: str,
    raw_keywords: List[str],
    subscribed_channel_ids: List[str] = None,
    clicked_video_titles: List[str] = None,
    initial_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    오늘 수집된 키워드를 받아 전체 AI 파이프라인 실행 후 뉴스레터 데이터 반환.

    Args:
        user_id:                  사용자 ID (google_id)
        raw_keywords:             오늘 수집된 검색어/영상 제목 전체
        subscribed_channel_ids:   사용자 구독 채널 ID 목록
        clicked_video_titles:     오늘 클릭/시청한 영상 제목 목록 (intent 판단용)
        initial_intent:           온보딩 설정 초기 의도 — 로그 부족 시 intent_ai 폴백으로 사용

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

    # ── Step 0: 의도 분류 (format_style 포함) ─────────────────────────────────
    # classify_intent()가 FORMAT_MAP 딕셔너리 조회까지 내부에서 처리하므로
    # decide_format() 별도 호출 불필요. ThreadPoolExecutor도 제거.
    print("[orchestrator] Step 0 — 의도 분류")
    intent_result = classify_intent(raw_keywords, clicked_video_titles)

    intent_type = intent_result.get("intent_type") or initial_intent or "지식형"
    format_style = intent_result["format_style"]
    print(f"[orchestrator] 의도={intent_type} / 길이={format_style['length']}")

    # ── Step 1: 주제 클러스터링 ────────────────────────────────────────────────
    print(f"[orchestrator] Step 1 — 주제 클러스터링 ({len(raw_keywords)}개 키워드)")
    clusters = cluster_topics(raw_keywords)
    if not clusters:
        raise ValueError("클러스터링 결과 없음 — 키워드 부족")

    print(f"[orchestrator] 클러스터 {len(clusters)}개 생성됨")

    # ── Step 2, 3: 주제별 순차 처리 ───────────────────────────────────────────
    # Gemini 무료 티어 일일 20회 제한으로 병렬 처리 대신 순차 처리
    analyses = []
    for cluster in clusters:
        topic = cluster["topic"]
        print(f"[orchestrator] Step 2 — 영상 선정: '{topic}'")

        videos = select_top_videos(
            topic=topic,
            subscribed_channel_ids=subscribed_channel_ids,
        )
        if not videos:
            print(f"  [스킵] '{topic}' 영상 없음")
            continue

        print(f"[orchestrator] Step 3 — 영상 분석: '{topic}' ({len(videos)}개)")
        try:
            analysis = analyze_videos(
                keyword=topic,
                videos=videos,
            )
            analyses.append(analysis)
        except Exception as e:
            print(f"  [스킵] '{topic}' — 분석 오류: {e}")
            continue

    if not analyses:
        raise ValueError("분석 가능한 주제 없음")

    # ── Step 4: 뉴스레터 생성 ──────────────────────────────────────────────────
    print(f"[orchestrator] Step 4 — 뉴스레터 생성 ({len(analyses)}개 주제 / 의도={intent_type})")
    newsletter = generate_newsletter(
        user_id=user_id,
        analyses=analyses,
        format_style=format_style,
        intent_type=intent_type,
    )

    print(f"[orchestrator] 완료 — {len(analyses)}개 주제 / 의도={intent_type}")
    return newsletter
