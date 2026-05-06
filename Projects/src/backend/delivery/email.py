import os
from typing import Dict, Any, List
from dotenv import load_dotenv

import resend

load_dotenv()
from logger import get_logger
logger = get_logger(__name__)

RESEND_API_KEY   = os.getenv("RESEND_API_KEY")
RESEND_FROM      = os.getenv("RESEND_FROM_EMAIL", "curator@tubify.com")

resend.api_key = RESEND_API_KEY


_INTENT_COLOR = {
    "유희형": "#FF6B35",
    "지식형": "#4A90D9",
    "구매형": "#27AE60",
}

_INTENT_LABEL = {
    "유희형": "😄 엔터테인먼트",
    "지식형": "🧠 지식 탐구",
    "구매형": "🛒 구매 가이드",
}


def _controversy_badges(controversies: List[str], accent: str) -> str:
    """쟁점 목록 → 뱃지 HTML. 없으면 빈 문자열 반환."""
    if not controversies:
        return ""
    badges = "".join(
        f'<span style="display:inline-block; background:rgba(231,76,60,0.1); '
        f'color:#c0392b; border:1px solid rgba(231,76,60,0.3); '
        f'border-radius:20px; padding:3px 10px; font-size:0.78em; '
        f'font-weight:600; margin:3px 4px 3px 0; line-height:1.4;">'
        f'⚡ {c}</span>'
        for c in controversies if c
    )
    return f'''
        <div style="margin-bottom:14px;">
          <div style="font-size:0.78em; font-weight:700; color:#c0392b;
                      text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">
            🔥 주요 쟁점
          </div>
          <div>{badges}</div>
        </div>'''


def _common_facts_block(common_facts: List[str]) -> str:
    """공통 사실 → HTML 블록. 없으면 빈 문자열."""
    if not common_facts:
        return ""
    items = "".join(
        f'<li style="margin-bottom:5px; color:#444;">{f}</li>'
        for f in common_facts if f
    )
    return f'''
        <div style="background:#eef4fb; border-radius:8px; padding:13px 14px;
                    margin-bottom:14px; border-left:3px solid #4A90D9;">
          <div style="font-weight:700; color:#2471a3; font-size:0.82em;
                      text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px;">
            📌 공통 사실
          </div>
          <ul style="margin:0; padding-left:18px; font-size:0.88em; line-height:1.7;">{items}</ul>
        </div>'''


def _source_cards(sources: List[Dict[str, Any]], accent: str) -> str:
    """출처 영상 목록 → 썸네일 + 채널명 포함 카드 HTML."""
    if not sources:
        return ""

    cards = []
    for s in sources:
        title         = s.get("title", "")
        url           = s.get("url", "#")
        channel_title = s.get("channel_title", "")
        thumbnail_url = s.get("thumbnail_url", "")

        thumb_html = (
            f'<img src="{thumbnail_url}" alt="" '
            f'style="width:100%; height:72px; object-fit:cover; '
            f'border-radius:6px 6px 0 0; display:block;">'
            if thumbnail_url else ""
        )
        channel_html = (
            f'<div style="font-size:0.75em; color:#888; margin-top:3px;">'
            f'📺 {channel_title}</div>'
            if channel_title else ""
        )

        cards.append(
            f'<a href="{url}" style="display:block; text-decoration:none; '
            f'background:#fff; border:1px solid #e8e8e8; border-radius:8px; '
            f'overflow:hidden; width:160px; flex-shrink:0; '
            f'transition:box-shadow 0.2s;">'
            f'{thumb_html}'
            f'<div style="padding:8px 10px;">'
            f'<div style="font-size:0.82em; color:#1a1a1a; font-weight:600; '
            f'line-height:1.4; display:-webkit-box; -webkit-line-clamp:2; '
            f'-webkit-box-orient:vertical; overflow:hidden;">▶ {title}</div>'
            f'{channel_html}'
            f'</div></a>'
        )

    return (
        '<div style="display:flex; gap:10px; overflow-x:auto; padding-bottom:4px;">' +
        "".join(cards) +
        '</div>'
    )


def _build_topic_card(topic_data: Dict[str, Any], accent: str) -> str:
    """주제 1개 → 카드형 HTML 블록 (썸네일, 채널명, 쟁점 배지, 공통 사실 포함)"""
    topic        = topic_data.get("topic", "")
    summary      = topic_data.get("summary", [])
    pros         = topic_data.get("pros", [])
    cons         = topic_data.get("cons", [])
    common_facts = topic_data.get("common_facts", [])
    controversies= topic_data.get("controversies", [])
    sources      = topic_data.get("sources", [])

    summary_items = "".join(
        f'<li style="margin-bottom:6px;">{s}</li>' for s in summary if s
    )
    pros_items = "".join(
        f'<li style="margin-bottom:4px;">{p}</li>' for p in pros if p
    )
    cons_items = "".join(
        f'<li style="margin-bottom:4px;">{c}</li>' for c in cons if c
    )

    pros_block = f'''
        <div style="flex:1; background:#f0faf4; border-radius:8px; padding:12px;">
          <div style="font-weight:700; color:#27AE60; margin-bottom:8px;">✅ 장점</div>
          <ul style="margin:0; padding-left:18px; color:#444; font-size:0.88em;">{pros_items}</ul>
        </div>''' if pros_items else ""

    cons_block = f'''
        <div style="flex:1; background:#fdf0f0; border-radius:8px; padding:12px;">
          <div style="font-weight:700; color:#E74C3C; margin-bottom:8px;">⚠️ 주의점</div>
          <ul style="margin:0; padding-left:18px; color:#444; font-size:0.88em;">{cons_items}</ul>
        </div>''' if cons_items else ""

    pros_cons_row = (
        f'<div style="display:flex; gap:12px; flex-wrap:wrap; margin-bottom:14px;">' +
        pros_block + cons_block +
        '</div>'
    ) if (pros_items or cons_items) else ""

    controversy_html  = _controversy_badges(controversies, accent)
    common_facts_html = _common_facts_block(common_facts)
    source_html       = _source_cards(sources, accent)

    return f'''
    <div style="background:#fff; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.08);
                margin-bottom:24px; overflow:hidden; border-top:4px solid {accent};">
      <!-- 주제 헤더 -->
      <div style="padding:20px 24px 14px;">
        <div style="font-size:1.05em; font-weight:800; color:#1a1a1a; margin-bottom:12px;">{topic}</div>

        <!-- 쟁점 배지 -->
        {controversy_html}

        <!-- 요약 -->
        <div style="background:#f8f9fa; border-radius:8px; padding:14px; margin-bottom:14px;">
          <div style="font-weight:700; color:#555; font-size:0.82em;
                      text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px;">
            📋 핵심 요약
          </div>
          <ul style="margin:0; padding-left:18px; color:#333; font-size:0.9em; line-height:1.7;">
            {summary_items}
          </ul>
        </div>

        <!-- 공통 사실 -->
        {common_facts_html}

        <!-- 장단점 -->
        {pros_cons_row}
      </div>

      <!-- 출처 영상 (썸네일 + 채널명) -->
      <div style="background:#f8f9fa; padding:14px 20px; border-top:1px solid #eee;">
        <div style="font-size:0.78em; color:#888; font-weight:600;
                    text-transform:uppercase; letter-spacing:0.5px; margin-bottom:10px;">
          🔗 출처 영상
        </div>
        {source_html}
      </div>
    </div>'''


def _format_html(newsletter: Dict[str, Any]) -> str:
    """뉴스레터 딕셔너리 → 카드형 HTML 이메일 본문"""
    subject      = newsletter.get("subject", "오늘의 유튜브 브리핑 🎬")
    intent_type  = newsletter.get("intent_type", "지식형")
    topics       = newsletter.get("topics", [])

    accent       = _INTENT_COLOR.get(intent_type, "#4A90D9")
    intent_label = _INTENT_LABEL.get(intent_type, "")

    cards = "".join(_build_topic_card(t, accent) for t in topics)

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0; padding:0; background:#f0f2f5; font-family:'Apple SD Gothic Neo',
             'Noto Sans KR', 'Segoe UI', sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5;">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px; width:100%;">

        <!-- 헤더 -->
        <tr><td style="background:{accent}; border-radius:12px 12px 0 0;
                        padding:28px 32px 24px;">
          <div style="color:rgba(255,255,255,0.8); font-size:0.78em;
                      font-weight:600; letter-spacing:0.5px; margin-bottom:6px;">
            ✦ Tubify &nbsp;·&nbsp; {intent_label}
          </div>
          <div style="color:#fff; font-size:1.4em; font-weight:800;
                      line-height:1.3;">
            {subject}
          </div>
        </td></tr>

        <!-- 본문 -->
        <tr><td style="background:#f0f2f5; padding:24px 0;">
          {cards}
        </td></tr>

        <!-- 푸터 -->
        <tr><td style="background:#fff; border-radius:0 0 12px 12px;
                        padding:20px 32px; text-align:center;">
          <p style="color:#aaa; font-size:0.78em; margin:0; line-height:1.6;">
            Tubify — 유튜브 알고리즘 대신, 오늘 당신이 관심 가진 주제를 분석해드립니다.<br>
            수신 거부는 대시보드에서 설정할 수 있습니다.
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>'''


def send_email(
    user_email: str,
    newsletter: Dict[str, Any],
) -> Dict[str, bool]:
    """
    Resend API를 통한 뉴스레터 발송

    INPUT:
      - user_email (str)  — 수신자 이메일
      - newsletter (Dict) — newsletter_ai 출력값

    OUTPUT:
      - {"success": bool}

    ENV:
      - RESEND_API_KEY   — Resend API 키 (필수)
      - RESEND_FROM_EMAIL — 발신자 주소 (기본: curator@tubify.com)
    """
    if not RESEND_API_KEY:
        logger.warning("[email] RESEND_API_KEY 없음 — 발송 스킵")
        return {"success": False}

    subject   = newsletter.get("subject", "오늘의 유튜브 브리핑 🎬")
    html_body = _format_html(newsletter)

    try:
        response = resend.Emails.send({
            "from":    RESEND_FROM,
            "to":      [user_email],
            "subject": subject,
            "html":    html_body,
        })
        logger.info(f"[email] 발송 성공 → {user_email} | id={response.get('id', '-')}")
        return {"success": True}

    except Exception as e:
        logger.error(f"[email] 발송 오류: {e}")
        return {"success": False}
