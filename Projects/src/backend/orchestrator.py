"""
orchestrator.py — 4개 AI 연결 파이프라인

흐름:
  [AI 1] selector_ai   → 영상 후보 선정 (top 5)
       ↓              ↘
  [AI 2] analyzer_ai   [AI 3] category_ai   (병렬 실행)
       ↓              ↙
  [AI 4] dashboard_ai  → 최종 대시보드 반환
"""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_EXCEPTION
from typing import List, Dict, Any

from agents.selector_ai import select_top_videos
from analyzer_ai import analyze_videos
from category_ai import classify_category
from dashboard_ai import generate_dashboard


def run_pipeline(
    keyword: str,
    subscribed_channel_ids: List[str] = None,
) -> Dict[str, Any]:
    """
    검색 키워드를 받아 전체 AI 파이프라인을 실행하고 대시보드 데이터를 반환.

    Args:
        keyword: 유튜브 검색 키워드
        subscribed_channel_ids: 사용자 구독 채널 ID 목록 (없으면 빈 리스트)

    Returns:
        dashboard_ai.generate_dashboard() 반환값
        {
            "keyword", "category", "layout",
            "summary_lines", "common_conclusion",
            "controversies", "recommended_videos", "common_facts"
        }

    Raises:
        ValueError: 영상을 찾을 수 없는 경우
    """
    if subscribed_channel_ids is None:
        subscribed_channel_ids = []

    print(f"[orchestrator] Step 1 — 영상 선정: '{keyword}'")
    videos = select_top_videos(
        topic=keyword,
        subscribed_channel_ids=subscribed_channel_ids,
    )
    if not videos:
        raise ValueError(f"'{keyword}' 검색 결과 영상 없음")

    video_titles = [v["title"] for v in videos]

    print("[orchestrator] Step 2+3 — 영상 분석 & 카테고리 분류 (병렬)")
    analyzer_result: Dict[str, Any] = {}
    category_result: Dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_analyzer = executor.submit(analyze_videos, keyword, videos)
        future_category = executor.submit(classify_category, keyword, video_titles)

        done, _ = wait(
            [future_analyzer, future_category],
            return_when=FIRST_EXCEPTION,
        )


        for f in done:
            if f.exception():
                raise f.exception()

        analyzer_result = future_analyzer.result()
        category_result = future_category.result()

    print("[orchestrator] Step 4 — 대시보드 생성")
    dashboard = generate_dashboard(
        keyword=keyword,
        selector_result=videos,
        analyzer_result=analyzer_result,
        category_result=category_result,
    )

    print(f"[orchestrator] 완료 — '{keyword}'")
    return dashboard
