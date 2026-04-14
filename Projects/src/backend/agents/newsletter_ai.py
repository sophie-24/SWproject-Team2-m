# backend/agents/newsletter_ai.py
"""
[AI 4] newsletter_ai.py — 뉴스레터 생성

역할:
- analyzer_ai 출력값을 받아 카톡/이메일용 뉴스레터 생성
- 주제별 3줄 요약, 장단점, 출처 링크 포함
"""

from typing import List, Dict, Any

from agents.gemini_client import call_gemini, parse_bullet_list


def _generate_topic_content(
    topic: str,
    analysis: Dict[str, Any],
    delivery_type: str,
) -> Dict[str, Any]:
    """
    주제 1개에 대한 뉴스레터 콘텐츠 생성

    - 3줄 요약
    - 장점 / 단점
    - 출처 영상 링크
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

    # 카톡은 간결하게, 이메일은 상세하게
    length_guide = "각 항목은 최대 1줄로 간결하게" if delivery_type == "kakao" else "각 항목은 2줄 이내로"

    prompt = f"""
검색 주제: {topic}

[공통 사실]
{facts_text}

[쟁점]
{controversy_text}

위 정보를 바탕으로 뉴스레터 콘텐츠를 작성하세요.
{length_guide} 작성하세요.

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
    delivery_type: str = "email",
) -> Dict[str, Any]:
    """
    analyzer_ai 출력값들을 받아 최종 뉴스레터 생성.

    INPUT:
      - user_id       (str)
      - analyses      (List[Dict]) — analyzer_ai 출력값 (주제별)
      - delivery_type ("kakao" | "email")

    OUTPUT:
      - newsletter: Dict
        {
          "subject": "오늘의 유튜브 브리핑 🎬",
          "topics": [
            {
              "topic":   "토리든 저분자 세럼",
              "summary": ["3줄 요약1", "3줄 요약2", "3줄 요약3"],
              "pros":    [...],
              "cons":    [...],
              "sources": [
                {
                  "title": "회사원언니 리뷰",
                  "url":   "https://youtube.com/watch?v=abc123"
                }
              ]
            }
          ]
        }
    """
    print(f"[newsletter_ai] 뉴스레터 생성 시작 — {len(analyses)}개 주제 / {delivery_type}")

    topics_content = []
    for analysis in analyses:
        topic = analysis.get("keyword") or analysis.get("topic", "")
        if not topic:
            continue

        content = _generate_topic_content(
            topic=topic,
            analysis=analysis,
            delivery_type=delivery_type,
        )
        topics_content.append(content)

    print(f"[newsletter_ai] 완료 — {len(topics_content)}개 주제 뉴스레터 생성")

    return {
        "subject": "오늘의 유튜브 브리핑 🎬",
        "topics":  topics_content,
    }