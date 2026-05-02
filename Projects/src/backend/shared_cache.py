# Pipeline A/B 공유 인메모리 분석 캐시 — search_analysis_cache 싱글턴 딕셔너리
"""
shared_cache.py — Pipeline A/B 공유 인메모리 캐시

Pipeline A (side panel) 분석 결과를 Pipeline B (newsletter)가 재활용해
Gemini 호출을 줄이기 위한 모듈 레벨 공유 상태.

Redis 도입 전 임시 구현 — 단일 워커 환경에서만 안전.

캐시 키: keyword 문자열 (소문자 strip)
캐시 값: dashboard_ai.generate_dashboard() 반환값
  {
    "keyword", "category", "layout",
    "summary_lines", "common_conclusion",
    "controversies", "recommended_videos", "common_facts"
  }
"""

search_analysis_cache: dict = {}  # { keyword: dashboard_result }
"""Pipeline A 분석 결과 캐시. main.py의 _search_analysis_cache와 동일 객체를 공유."""
