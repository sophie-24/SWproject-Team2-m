from collections import Counter


def get_triggered_topics(today_logs: list[dict], threshold: int = 2) -> list[str]:
    """
    오늘 수집된 행동 로그에서 2회 이상 등장한 주제(키워드)를 반환

    INPUT:
      - today_logs (List[Dict]) — behavior_store.get_today_logs() 출력값
      - threshold  (int)        — 트리거 기준 횟수 (기본 2회)

    OUTPUT:
      - triggered_topics: List[str]
        예: ["토리든 저분자 세럼", "아이폰 16 리뷰"]
    """
    if not today_logs:
        return []

    # 키워드 빈도 카운트
    keyword_counts = Counter(log["keyword"] for log in today_logs)

    # threshold 이상인 키워드만 추출
    triggered = [
        keyword
        for keyword, count in keyword_counts.items()
        if count >= threshold
    ]

    return triggered
