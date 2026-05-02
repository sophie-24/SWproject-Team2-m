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

<<<<<<< Updated upstream

def _build_length_guide(format_style: Optional[Dict[str, str]]) -> str:
    """format_style.length를 기반으로 길이 지시문 반환."""
    if format_style and format_style.get("length") == "short":
        return "각 항목은 1줄로 간결하게"
    return "각 항목은 2줄 이내로"


def _generate_topic_content(
    topic: str,
    analysis: Dict[str, Any],
    format_style: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    주제 1개에 대한 뉴스레터 콘텐츠 생성.

    Args:
        topic:        검색 주제
        analysis:     analyzer_ai 출력값
        format_style: format_ai.decide_format() 반환값 (없으면 기본 스타일 적용)
    """
    videos = analysis.get("videos", [])
    common_facts = analysis.get("common_facts", [])
    controversies = analysis.get("controversies", [])

    # 광고 탐지된 영상 제외 후 출처 구성
    sources = [
        {
            "title": v["title"],
            "url":   f"https://youtube.com/watch?v={v['video_id']}",
        }
        for v in videos
        if not v.get("ad_detected", False) and v.get("transcript_available", False)
    ]

    # 출처가 없으면 전체 영상 사용
    if not sources:
        sources = [
            {
                "title": v["title"],
                "url":   f"https://youtube.com/watch?v={v['video_id']}",
            }
            for v in videos
        ]

    facts_text = "\n".join(f"- {f}" for f in common_facts) or "- 없음"
    controversy_text = "\n".join(f"- {c}" for c in controversies) or "- 없음"

    length_guide = _build_length_guide(format_style)

    # format_style 지시문 구성
    tone_guide = format_style.get("tone", "") if format_style else ""
    structure_guide = format_style.get("structure", "") if format_style else ""
    style_block = ""
    if tone_guide or structure_guide:
        style_block = f"""
[작성 스타일]
{tone_guide}
{structure_guide}
""".strip()

    prompt = f"""
검색 주제: {topic}

[공통 사실]
{facts_text}

[쟁점]
{controversy_text}

위 정보를 바탕으로 뉴스레터 콘텐츠를 작성하세요.
{length_guide} 작성하세요.
{style_block}

[요약]
이 주제의 핵심을 3줄로 요약.
각 줄은 "- " 으로 시작. 정확히 3개.

[장점]
이 주제에서 긍정적인 점을 최대 3개.
각 항목은 "- " 으로 시작.

[단점]
이 주제에서 부정적이거나 주의할 점을 최대 3개.
각 항목은 "- " 으로 시작.
"""

    try:
        text = call_gemini(prompt)
    except Exception as e:
        print(f"[newsletter_ai] '{topic}' 생성 오류: {e}")
        return {
            "topic":   topic,
            "summary": ["요약 생성 실패", "", ""],
            "pros":    [],
            "cons":    [],
            "sources": sources,
        }

    summary = parse_bullet_list(text, "요약")
    pros    = parse_bullet_list(text, "장점")
    cons    = parse_bullet_list(text, "단점")

    # 요약 정확히 3줄 보장
    while len(summary) < 3:
        summary.append("")
    summary = summary[:3]

    return {
        "topic":   topic,
        "summary": summary,
        "pros":    pros,
        "cons":    cons,
        "sources": sources,
    }


def generate_newsletter(
=======
# format_style.length -> summary 최대 줄 수
_SUMMARY_LEN = {"short": 1, "medium": 2, "long": 3}


async def generate_newsletter(
>>>>>>> Stashed changes
    user_id: str,
    analyses: List[Dict[str, Any]],
    format_style: Optional[Dict[str, str]] = None,
    intent_type: str = "지식형",
) -> Dict[str, Any]:
    """
    analyzer_ai 출력값들을 intent_type에 맞게 조립해 최종 뉴스레터를 반환.
    Gemini 호출 없음.

<<<<<<< Updated upstream
    INPUT:
      - user_id       (str)
      - analyses      (List[Dict])        — analyzer_ai 출력값 (주제별)
      - format_style  (Dict, optional)    — format_ai.decide_format() 반환값
      - intent_type   (str, optional)     — 제목 이모지 결정용

    OUTPUT:
      {
        "subject": "오늘의 유튜브 브리핑 🎬",
        "intent_type": "지식형",
        "topics": [
          {
            "topic":   str,
            "summary": [str, str, str],
            "pros":    List[str],
            "cons":    List[str],
            "sources": [{"title": str, "url": str}]
          }
        ]
      }
=======
    의도별 차이:
      유희형 - 짧고 임팩트 있게, controversies 강조, pros/cons 생략
      지식형 - 배경->핵심->시사점, common_facts + controversies + pros/cons 모두 포함
      구매형 - pros/cons 명확 분리, common_facts 포함, controversies 생략
>>>>>>> Stashed changes
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
