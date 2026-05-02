# -*- coding: utf-8 -*-
# 주제 클러스터링 에이전트 — 오늘 검색어를 시간 흐름 컨텍스트 포함해 의미 기반 그룹화
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from gemini_client import call_gemini_async

from logger import get_logger
logger = get_logger(__name__)


MAX_TOPICS = 5
MIN_TOPICS = 3


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────

def _parse_hour(logged_at) -> Optional[int]:
    """logged_at(datetime or str) → 0~23 시간 반환. 실패 시 None."""
    try:
        if not isinstance(logged_at, datetime):
            logged_at = datetime.fromisoformat(str(logged_at))
        if logged_at.tzinfo is None:
            logged_at = logged_at.replace(tzinfo=timezone.utc)
        # KST (+9) 기준으로 표시
        return (logged_at.hour + 9) % 24
    except Exception:
        return None


def _build_time_context(today_logs: List[Dict[str, Any]]) -> str:
    """
    today_logs → 시간대별 키워드 요약 문자열 생성 (Gemini 프롬프트용).

    예:
      오전 9시: 아이폰16, 아이폰 카메라 리뷰
      오전 11시: 맥북 M4, 맥북 프로 리뷰
      오후 2시: 아이폰16 리뷰, 아이폰16 vs 갤럭시
    """
    hour_buckets: Dict[int, List[str]] = defaultdict(list)

    for log in today_logs:
        kw = log.get("keyword", "").strip()
        if not kw:
            continue
        hour = _parse_hour(log.get("logged_at"))
        if hour is None:
            continue
        # 같은 시간대에 중복 키워드 제외
        if kw not in hour_buckets[hour]:
            hour_buckets[hour].append(kw)

    if not hour_buckets:
        return ""

    lines = []
    for hour in sorted(hour_buckets.keys()):
        label = f"오전 {hour}시" if hour < 12 else (
            "정오" if hour == 12 else f"오후 {hour - 12}시"
        )
        lines.append(f"  {label}: {', '.join(hour_buckets[hour])}")
    return "\n".join(lines)


def _enrich_clusters(
    clusters: List[Dict[str, Any]],
    today_logs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    clusters의 각 topic에 시간 메타데이터 부착.

    추가 필드:
      - first_seen  (str)  "HH:MM" KST — 관련 키워드 첫 등장 시각
      - last_seen   (str)  "HH:MM" KST — 마지막 등장 시각
      - peak_hour   (int)  0~23  KST — 가장 많이 검색된 시간대
      - event_count (int)  해당 클러스터 키워드의 총 이벤트 수
    """
    # keyword → 로그 목록 매핑
    kw_logs: Dict[str, List[Dict]] = defaultdict(list)
    for log in today_logs:
        kw = log.get("keyword", "").strip()
        if kw:
            kw_logs[kw].append(log)

    enriched = []
    for cluster in clusters:
        topic_keywords = set(cluster.get("keywords", []))
        related_logs = [
            log for kw in topic_keywords for log in kw_logs.get(kw, [])
        ]

        if not related_logs:
            enriched.append({**cluster, "first_seen": None, "last_seen": None,
                              "peak_hour": None, "event_count": 0})
            continue

        # 시각 파싱
        times = []
        for log in related_logs:
            try:
                dt = log.get("logged_at")
                if not isinstance(dt, datetime):
                    dt = datetime.fromisoformat(str(dt))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                times.append(dt)
            except Exception:
                pass

        if not times:
            enriched.append({**cluster, "first_seen": None, "last_seen": None,
                              "peak_hour": None, "event_count": len(related_logs)})
            continue

        times.sort()
        first = times[0]
        last  = times[-1]

        def to_kst_str(dt: datetime) -> str:
            kst_hour = (dt.hour + 9) % 24
            return f"{kst_hour:02d}:{dt.minute:02d}"

        # peak_hour: 이벤트가 가장 많이 몰린 KST 시간대
        hour_counts: Dict[int, int] = defaultdict(int)
        for dt in times:
            hour_counts[(dt.hour + 9) % 24] += 1
        peak_hour = max(hour_counts, key=lambda h: hour_counts[h])

        enriched.append({
            **cluster,
            "first_seen":  to_kst_str(first),
            "last_seen":   to_kst_str(last),
            "peak_hour":   peak_hour,
            "event_count": len(related_logs),
        })

<<<<<<< Updated upstream
    try:
        text = call_gemini(prompt, temperature=0.2)
        clusters = _parse_clusters(text)
    except Exception as e:
        print(f"[cluster_ai] Gemini 오류 — 폴백 실행: {e}")
        clusters = _fallback_cluster(unique_keywords)

    # 상한선 적용 (가장 관심도 높은 순 — Gemini가 이미 정렬해준다고 가정)
    clusters = clusters[:max_topics]

    print(f"[cluster_ai] 완료 — {len(clusters)}개 클러스터 생성")
    return clusters


def _parse_clusters(text: str) -> List[Dict[str, Any]]:
    """Gemini 응답에서 JSON 파싱"""
    # JSON 배열 추출
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("JSON 배열을 찾을 수 없음")
=======
    return enriched


def _parse_clusters(text: str) -> List[Dict[str, Any]]:
    """
    Gemini 응답에서 JSON 파싱.

    json_mode=True 덕분에 정상적으로는 순수 JSON이 오지만,
    마크다운 코드블록(```json ... ```)이 포함되더라도 안전하게 처리한다.
    """
    cleaned = re.sub(r"```(?:json)?\s*([\s\S]*?)```", r"\1", text).strip()
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"JSON 배열을 찾을 수 없음. 원본: {text[:200]!r}")
>>>>>>> Stashed changes

    clusters = json.loads(match.group())
    result = []
    for c in clusters:
        if "topic" in c and "keywords" in c:
            result.append({
                "topic":    str(c["topic"]).strip(),
                "keywords": [str(k).strip() for k in c["keywords"] if k],
            })
    if not result:
        raise ValueError("유효한 클러스터 없음")
    return result


def _fallback_cluster(keywords: List[str]) -> List[Dict[str, Any]]:
    """Gemini 호출 실패 시 폴백: 키워드를 각각 독립 클러스터로 처리."""
    return [{"topic": kw, "keywords": [kw]} for kw in keywords]


# ── 메인 함수 ──────────────────────────────────────────────────────────────────

async def cluster_topics(
    raw_keywords: List[str],
    max_topics: int = MAX_TOPICS,
    today_logs: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    오늘 수집된 검색어/영상 제목을 주제별로 클러스터링.

    today_logs가 제공되면 시간 흐름 컨텍스트를 Gemini 프롬프트에 포함하고,
    각 클러스터에 first_seen / last_seen / peak_hour / event_count 메타데이터를 부착한다.
    today_logs 없이 호출해도 기존과 동일하게 동작(메타데이터만 None 처리).

    INPUT:
      - raw_keywords : List[str] — 오늘 수집된 검색어/영상 제목 전체
      - max_topics   : int       — 최대 클러스터 수 (기본 5)
      - today_logs   : Optional[List[Dict]] — behavior_store.get_today_logs() 반환값
          [{event_type, keyword, video_id, logged_at}, ...]

    OUTPUT:
      - clusters: List[Dict] (최대 max_topics개)
        예: [
          {
            "topic":       "아이폰 16 카메라",
            "keywords":    ["아이폰16", "아이폰16 카메라"],
            "first_seen":  "09:15",
            "last_seen":   "14:32",
            "peak_hour":   9,
            "event_count": 4,
          },
          ...
        ]
    """
    if not raw_keywords:
        return []

    unique_keywords = list(dict.fromkeys(raw_keywords))
    logger.info(
        f"[cluster_ai] 클러스터링 시작 — {len(unique_keywords)}개 키워드, "
        f"최대 {max_topics}개 클러스터, 시간 컨텍스트={'있음' if today_logs else '없음'}"
    )

    keywords_text = "\n".join(f"- {kw}" for kw in unique_keywords)

    # 시간 흐름 컨텍스트 (today_logs 있을 때만 삽입)
    time_context_section = ""
    if today_logs:
        time_ctx = _build_time_context(today_logs)
        if time_ctx:
            time_context_section = f"""
아래는 같은 키워드들이 시간대별로 언제 검색됐는지를 나타냅니다.
시간 흐름을 고려해 지속적으로 관심을 보인 주제를 더 중요하게 묶어 주세요.

[시간대별 검색 흐름]
{time_ctx}
"""

    prompt = f"""다음은 사용자가 오늘 유튜브에서 검색하거나 시청한 키워드/영상 제목 목록입니다.

{keywords_text}
{time_context_section}
이 키워드들을 의미적으로 유사한 주제끼리 묶어 클러스터링하세요.

규칙:
1. 비슷한 주제끼리 하나의 클러스터로 묶으세요
2. 각 클러스터에 대표 주제명(topic)을 붙이세요
3. 주제명은 검색하기 좋은 간결한 한국어로 작성하세요
4. 클러스터 수는 최대 {max_topics}개로 제한하세요 (가장 관련성 높은 주제 우선)
5. 시간대가 제공된 경우, 더 반복적으로 검색된 주제를 앞에 배치하세요
6. 반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이)

응답 형식:
[
  {{
    "topic": "대표 주제명",
    "keywords": ["관련 키워드1", "관련 키워드2"]
  }}
]"""

    try:
        text = await call_gemini_async(prompt, temperature=0.2, json_mode=True)
        clusters = _parse_clusters(text)
    except Exception as e:
        logger.error(f"[cluster_ai] Gemini 오류 — 폴백 실행: {e}")
        clusters = _fallback_cluster(unique_keywords)

    clusters = clusters[:max_topics]

    # today_logs 있으면 시간 메타데이터 부착
    if today_logs:
        clusters = _enrich_clusters(clusters, today_logs)

    logger.info(f"[cluster_ai] 완료 — {len(clusters)}개 클러스터 생성")
    return clusters
