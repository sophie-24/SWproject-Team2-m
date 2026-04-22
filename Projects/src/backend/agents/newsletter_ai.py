from typing import List, Dict, Any, Optional

from agents.gemini_client import call_gemini, parse_bullet_list

# 의도 타입별 제목 이모지
_SUBJECT_EMOJI = {
    "유희형": "😄",
    "지식형": "🧠",
    "구매형": "🛒",
}


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
    user_id: str,
    analyses: List[Dict[str, Any]],
    format_style: Optional[Dict[str, str]] = None,
    intent_type: str = "지식형",
) -> Dict[str, Any]:
    """
    analyzer_ai 출력값들을 받아 최종 뉴스레터 생성.

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
    """
    emoji = _SUBJECT_EMOJI.get(intent_type, "🎬")
    print(
        f"[newsletter_ai] 뉴스레터 생성 시작 — "
        f"{len(analyses)}개 주제 / 의도={intent_type}"
    )

    topics_content = []
    for analysis in analyses:
        topic = analysis.get("keyword") or analysis.get("topic", "")
        if not topic:
            continue

        content = _generate_topic_content(
            topic=topic,
            analysis=analysis,
            format_style=format_style,
        )
        topics_content.append(content)

    print(f"[newsletter_ai] 완료 — {len(topics_content)}개 주제 뉴스레터 생성")

    return {
        "subject":     f"오늘의 유튜브 브리핑 {emoji}",
        "intent_type": intent_type,
        "topics":      topics_content,
    }
