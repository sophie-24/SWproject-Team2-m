# Pipeline A/B 공유 인메모리 분석 캐시 — search_analysis_cache 싱글턴 딕셔너리
"""
shared_cache.py — Pipeline A/B 공유 인메모리 캐시 (TTL 지원)

Pipeline A (side panel) 분석 결과를 Pipeline B (newsletter)가 재활용해
Gemini 호출을 줄이기 위한 모듈 레벨 공유 상태.

Redis 도입 전 임시 구현 — 단일 워커 환경에서만 안전.

캐시 키: keyword 문자열 (소문자 strip)
캐시 값: { "data": DashboardResult, "cached_at": float (unix timestamp) }
  data 내부:
    "keyword", "category", "layout", "intent_type",
    "summary_lines", "common_conclusion",
    "controversies", "recommended_videos", "common_facts"

TTL 전략 (Pipeline B 기준):
  0 ~ CACHE_TTL_SECONDS  : 신선 — intent_type 재활용 + 영상 새로 선정
  CACHE_TTL_SECONDS 초과 : 만료 — 캐시 무효화, 전체 새로 실행
"""

import time
from typing import Any, Optional

CACHE_TTL_SECONDS: int = 3600  # 1시간 — 필요 시 조정

search_analysis_cache: dict = {}  # { keyword: { "data": ..., "cached_at": float } }
"""Pipeline A 분석 결과 캐시. main.py의 _search_analysis_cache와 동일 객체를 공유."""


def _normalize_key(keyword: str) -> str:
    return keyword.strip().lower()


def get_cached(keyword: str) -> Optional[Any]:
    """
    TTL 검사 포함 캐시 조회.

    Returns:
        신선한 캐시가 있으면 DashboardResult dict 반환.
        없거나 만료됐으면 None 반환 (만료 시 자동 삭제).
    """
    key   = _normalize_key(keyword)
    entry = search_analysis_cache.get(key)
    if not entry:
        return None
    if time.time() - entry["cached_at"] > CACHE_TTL_SECONDS:
        search_analysis_cache.pop(key, None)
        return None
    return entry["data"]


def set_cached(keyword: str, data: dict) -> None:
    """타임스탬프와 함께 캐시에 저장."""
    key = _normalize_key(keyword)
    search_analysis_cache[key] = {
        "data":      data,
        "cached_at": time.time(),
    }
