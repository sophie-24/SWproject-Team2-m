from typing import List, Dict, Any, Optional

from agents.gemini_client import call_gemini, parse_bullet_list

# 의도 타입별 제목 이모지
_SUBJECT_EMOJI = {
    "유희형": "😄",
    "지식형": "🧠",
    "구매형": "🛒",
}

# 신뢰도 기준: 이 값 이상이면 "신뢰도 높음"으로 분류
_HIGH_CREDIBILITY_THRESHOLD = 0.7


def _build_length_guide(format_style: Optional[Dict[str, str]]) -> str:
    """format_style.length를 기반으로 길이 지시문 반환."""
    if format_style and format_style.get("length") == "short":
        return "각 항목은 1줄로 간결하게"
    return "각 항목은 2줄 이내로"


def _build_credibility_block(videos: List[Dict[str, Any]]) -> str:
    """
    영상별 key_claims를 credibility_score 기준으로 두 그룹으로 분리해
    Gemini 프롬프트에 삽입할 텍스트 블록을 만든다.

    - 신뢰도 높음 (credibility_score >= 0.7, 광고 미감지): 핵심 근거로 활용
    - 참고용 (그 외): 보조 정보로만 활용

    analyzer_ai에서 계산된 credibility_score와 key_claims가
    newsletter 프롬프트에 전달되지 않아 신뢰도 정보가 완전히 소실되던 문제를 해결.
    """
    high, low = [], []
    for v in videos:
        if not v.get("key_claims"):
            continue
        is_high = (
            v.get("credibility_score", 0) >= _HIGH_CREDIBILITY_THRESHOLD
            and not v.get("ad_detected", False)
        )
        (high if is_high else low).append(v)

    lines = []

    if high:
        lines.append("[신뢰도 높은 출처] — 요약과 장단점 작성 시 이 주장을 우선 반영하세요.")
        for v in high:
            score = v.get("credibility_score", 0)
            lines.append(f"  채널: {v['channel_title']} (신뢰도 {score:.2f})")
            for claim in v["key_claims"]:
                lines.append(f"    - {claim}")

    if low:
        lines.append("[참고용 출처] — 보조 정보로만 활용하고, 신뢰도 높은 출처와 상충 시 우선순위를 낮추세요.")
        for v in low:
            score = v.get("credibility_score", 0)
            ad_note = " (광고 포함)" if v.get("ad_detected") else ""
            lines.append(f"  채널: {v['channel_title']} (신뢰도 {score:.2f}{ad_note})")
            for claim in v["key_claims"]:
                lines.append(f"    - {claim}")

    return "\n".join(lines) if lines else ""


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
        format_style: intent_ai가 반환한 format_style (없으면 기본 스타일 적용)
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

    # 신뢰도별 출처 블록 (핵심 개선: credibility_score가 프롬프트에 반영됨)
    credibility_block = _build_credibility_block(videos)

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

    # 신뢰도 블록이 있을 때만 프롬프트에 포함
    credibility_section = ""
    if credibility_block:
        credibility_section = f"""
[영상별 주장 (신뢰도 등급별)]
{credibility_block}

"""

    prompt = f"""
검색 주제: {topic}
{credibility_section}
[공통 사실] — 여러 영상에서 공통으로 확인된 정보
{facts_text}

[쟁점] — 영상마다 의견이 갈리는 내용
{controversy_text}

위 정보를 바탕으로 뉴스레터 콘텐츠를 작성하세요.
신뢰도 높은 출처의 주장을 중심으로 서술하고, 참고용 출처는 보조 정보로만 활용하세요.
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
      - format_style  (Dict, optional)    — intent_ai가 반환한 format_style
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
