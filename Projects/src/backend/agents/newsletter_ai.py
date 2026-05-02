# -*- coding: utf-8 -*-
# 뉴스레터 조립 에이전트 — analyzer 결과를 의도 타입별(유희형·지식형·구매형)로 조립해 최종 데이터 반환
from typing import List, Dict, Any, Optional
from logger import get_logger
logger = get_logger(__name__)

_SUBJECT_TEMPLATES = {
    "유희형": "오늘 유튜브에서 화제였던 것들 😄",
    "지식형": "오늘의 유튜브 지식 브리핑 🧠",
    "구매형": "오늘의 구매 판단 가이드 🛒",
}
_DEFAULT_SUBJECT = "오늘의 유튜브 브리핑 🎬"

# format_style.length -> summary 최대 줄 수
_SUMMARY_LEN = {"short": 1, "medium": 2, "long": 3}


async def generate_newsletter(
    user_id: str,
    analyses: List[Dict[str, Any]],
    format_style: Optional[Dict[str, str]] = None,
    intent_type: str = "지식형",
) -> Dict[str, Any]:
    """
    analyzer_ai 출력값들을 intent_type에 맞게 조립해 최종 뉴스레터를 반환.
    Gemini 호출 없음.

    의도별 차이:
      유희형 - 짧고 임팩트 있게, controversies 강조, pros/cons 생략
      지식형 - 배경->핵심->시사점, common_facts + controversies + pros/cons 모두 포함
      구매형 - pros/cons 명확 분리, common_facts 포함, controversies 생략
    """
    if format_style is None:
        format_style = {}

    length_hint = format_style.get("length", "long")
    max_summary = _SUMMARY_LEN.get(length_hint, 3)
    subject = _SUBJECT_TEMPLATES.get(intent_type, _DEFAULT_SUBJECT)
    logger.info(f"[newsletter_ai] 조립 시작 -- {len(analyses)}개 주제 / 의도={intent_type} / 길이={length_hint}")

    topics_content = []
    for analysis in analyses:
        topic = analysis.get("keyword") or analysis.get("topic", "")
        if not topic:
            continue

        raw_summary = analysis.get("summary", [])
        while len(raw_summary) < 3:
            raw_summary.append("")
        summary = [s for s in raw_summary[:max_summary] if s]

        topic_block = _build_topic_block(
            topic=topic,
            summary=summary,
            pros=analysis.get("pros", []),
            cons=analysis.get("cons", []),
            common_facts=analysis.get("common_facts", []),
            controversies=analysis.get("controversies", []),
            sources=analysis.get("sources", []),
            intent_type=intent_type,
        )
        topics_content.append(topic_block)

    logger.info(f"[newsletter_ai] 완료 -- {len(topics_content)}개 주제")
    return {
        "subject":     subject,
        "intent_type": intent_type,
        "topics":      topics_content,
    }


def _build_topic_block(
    topic: str,
    summary: List[str],
    pros: List[str],
    cons: List[str],
    common_facts: List[str],
    controversies: List[str],
    sources: List[Dict[str, str]],
    intent_type: str,
) -> Dict[str, Any]:
    """의도 타입에 따라 포함할 필드를 결정해 topic 블록 반환."""
    base = {"topic": topic, "summary": summary, "sources": sources}

    if intent_type == "유희형":
        # 가볍고 재밌게 -- 쟁점/화제만 부각
        base["controversies"] = controversies
        base["pros"]         = []
        base["cons"]         = []
        base["common_facts"] = []

    elif intent_type == "구매형":
        # 실용적 비교 -- pros/cons + 객관적 근거
        base["pros"]          = pros
        base["cons"]          = cons
        base["common_facts"]  = common_facts
        base["controversies"] = []

    else:
        # 지식형 (기본) -- 모든 정보 포함
        base["common_facts"]  = common_facts
        base["controversies"] = controversies
        base["pros"]          = pros
        base["cons"]          = cons

    return base
