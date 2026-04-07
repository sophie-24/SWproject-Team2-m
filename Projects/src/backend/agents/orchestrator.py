"""
orchestrator.py — v3 멀티 에이전트 파이프라인

흐름:
  [AI 1] cluster_ai    → 주제 클러스터링
       ↓
  [AI 2] selector_ai   → 주제별 영상 후보 선정 (top 5)
       ↓
  [AI 3] analyzer_ai   → 자막 분석 + 광고 탐지
       ↓
  [AI 4] newsletter_ai → 뉴스레터 생성
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from typing import List, Dict, Any

from agents.cluster_ai import cluster_topics
from agents.selector_ai import select_top_videos
from agents.analyzer_ai import analyze_videos
from agents.newsletter_ai import generate_newsletter


def run_pipeline(
    user_id: str,
    raw_keywords: List[str],
    subscribed_channel_ids: List[str] = None,
    delivery_type: str = "email",
) -> Dict[str, Any]:
    """
    오늘 수집된 키워드를 받아 전체 AI 파이프라인 실행 후 뉴스레터 데이터 반환.

    Args:
        user_id:                  사용자 ID
        raw_keywords:             오늘 수집된 검색어/영상 제목 전체 (cluster_ai 입력)
        subscribed_channel_ids:   사용자 구독 채널 ID 목록
        delivery_type:            'kakao' | 'email'

    Returns:
        newsletter_ai.generate_newsletter() 반환값
        {
            "subject", "topics": [
                {"topic", "summary", "pros", "cons", "sources"}
            ]
        }

    Raises:
        ValueError: 클러스터링 결과가 없거나 영상을 찾을 수 없는 경우
    """
    if subscribed_channel_ids is None:
        subscribed_channel_ids = []

    # ── Step 1: 주제 클러스터링 ────────────────────────────
    print(f"[orchestrator] Step 1 — 주제 클러스터링 ({len(raw_keywords)}개 키워드)")
    clusters = cluster_topics(raw_keywords)
    if not clusters:
        raise ValueError("클러스터링 결과 없음 — 키워드 부족")

    print(f"[orchestrator] 클러스터 {len(clusters)}개 생성됨")

    # ── Step 2, 3: 주제별 순차 처리 ───────────────────────
    # Gemini 무료 티어 일일 20회 제한으로 병렬 처리 대신 순차 처리
    analyses = []
    for cluster in clusters:
        topic = cluster["topic"]
        print(f"[orchestrator] Step 2 — 영상 선정: '{topic}'")

        # Step 2: 영상 선정
        videos = select_top_videos(
            topic=topic,
            subscribed_channel_ids=subscribed_channel_ids,
        )
        if not videos:
            print(f"  [스킵] '{topic}' 영상 없음")
            continue

        # Step 3: 영상 분석
        print(f"[orchestrator] Step 3 — 영상 분석: '{topic}' ({len(videos)}개)")
        try:
            analysis = analyze_videos(
                keyword=topic,
                videos=videos,
            )
            analyses.append(analysis)  # ← try 안으로 들여쓰기
        except Exception as e:
            print(f"  [스킵] '{topic}' — 분석 오류: {e}")
            continue

    
    if not analyses:
        raise ValueError("분석 가능한 주제 없음")

    # ── Step 4: 뉴스레터 생성 ──────────────────────────────
    print(f"[orchestrator] Step 4 — 뉴스레터 생성 ({len(analyses)}개 주제)")
    newsletter = generate_newsletter(
        user_id=user_id,
        analyses=analyses,
        delivery_type=delivery_type,
    )

    print(f"[orchestrator] 완료 — {len(analyses)}개 주제 뉴스레터 생성")
    return newsletter