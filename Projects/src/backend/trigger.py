# 행동 로그 기반 뉴스레터 주제 트리거 판단 — 시간 감쇠(반감기 4h) + 연속 시청 보너스 가중치
"""
trigger.py -- 행동 로그 기반 뉴스레터 트리거 판단

단순 빈도 카운트에서 3가지 신호를 종합한 가중치 점수 방식으로 개선.

  1. 시간 감쇠 (Recency Decay)
     - 최근 활동일수록 높은 가중치, 지수 감쇠 (반감기 4시간)
     - 낮에 잠깐 봤다가 잊은 주제는 자연스럽게 점수 낮아짐

  2. 연속 시청 감지 (Consecutive Watch Bonus)
     - 동일 키워드로 watch 이벤트가 2회 이상 연속 -> +0.5 보너스
     - 이것저것 훑어보는 것과 집중해서 파는 것을 구분

  3. 가중치 임계값 (Weighted Threshold)
     - 정수 카운트(>=2) 대신 float 점수 합산(>=1.5)
     - 최근 2회 이벤트도 통과, 오래된 단순 2회는 걸러냄
"""

import math
from collections import defaultdict
from datetime import datetime, timezone


# -- 파라미터 -------------------------------------------------------------------

DECAY_HALF_LIFE_HOURS = 4.0   # 감쇠 반감기: 4시간 전 이벤트는 가중치 0.5배
CONSECUTIVE_BONUS     = 0.5   # 연속 시청 시 추가 보너스
DEFAULT_THRESHOLD     = 1.5   # 기본 트리거 임계값


# -- 내부 헬퍼 ------------------------------------------------------------------

def _recency_weight(logged_at, now: datetime) -> float:
    """
    이벤트 발생 시각으로부터 지금까지의 경과 시간을 기반으로 0~1 사이 가중치 반환.
    공식: exp(-ln2 * hours_ago / half_life)

    examples:
      - 방금 (0시간) -> 1.00
      - 1시간 전     -> 0.84
      - 4시간 전     -> 0.50  (반감기)
      - 8시간 전     -> 0.25
    """
    try:
        if not isinstance(logged_at, datetime):
            logged_at = datetime.fromisoformat(str(logged_at))
        if logged_at.tzinfo is None:
            logged_at = logged_at.replace(tzinfo=timezone.utc)
        hours_ago = max(0.0, (now - logged_at).total_seconds() / 3600)
        return math.exp(-math.log(2) * hours_ago / DECAY_HALF_LIFE_HOURS)
    except Exception:
        return 0.5  # 파싱 실패 시 중간값


def _detect_consecutive_watches(logs: list) -> set:
    """
    연속 시청 감지: 동일 키워드 watch 이벤트가 직전 이벤트와 연속일 때 해당 키워드 반환.
    logs는 logged_at 기준 오름차순 정렬을 가정.
    """
    consecutive = set()
    prev_keyword = ""
    prev_event   = ""

    for log in logs:
        kw = log.get("keyword", "").strip()
        ev = log.get("event_type", "")
        if ev == "watch" and prev_event == "watch" and kw == prev_keyword and kw:
            consecutive.add(kw)
        prev_keyword = kw
        prev_event   = ev

    return consecutive


# -- 메인 함수 ------------------------------------------------------------------

def get_triggered_topics(
    today_logs: list,
    threshold:  float = DEFAULT_THRESHOLD,
) -> list:
    """
    오늘 수집된 행동 로그에서 가중치 점수가 threshold 이상인 키워드를 반환.

    INPUT:
      - today_logs: behavior_store.get_today_logs() 출력값
        [{ "event_type", "keyword", "video_id", "logged_at" }, ...]
      - threshold: 트리거 기준 점수 (기본 1.5)
        대략 최근 2회 이상, 또는 연속 시청 1회 + 추가 1회 수준

    OUTPUT:
      - 가중치 내림차순 정렬된 키워드 목록
        예: ["아이폰 16 리뷰", "토리든 세럼"]
    """
    if not today_logs:
        return []

    now = datetime.now(timezone.utc)

    # 1) 시간 감쇠 가중치 합산
    keyword_scores = defaultdict(float)
    for log in today_logs:
        kw = log.get("keyword", "").strip()
        if not kw:
            continue
        keyword_scores[kw] += _recency_weight(log.get("logged_at", ""), now)

    # 2) 연속 시청 보너스 적용
    for kw in _detect_consecutive_watches(today_logs):
        if kw in keyword_scores:
            keyword_scores[kw] += CONSECUTIVE_BONUS

    # 3) 임계값 필터 + 점수 내림차순 정렬
    triggered = [
        kw
        for kw, score in sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
        if score >= threshold
    ]

    return triggered
