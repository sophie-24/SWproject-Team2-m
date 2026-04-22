import os
from typing import Dict, Any
from dotenv import load_dotenv

import resend

load_dotenv()

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


def _build_topic_card(topic_data: Dict[str, Any], accent: str) -> str:
    """주제 1개 → 카드형 HTML 블록"""
    topic   = topic_data.get("topic", "")
    summary = topic_data.get("summary", [])
    pros    = topic_data.get("pros", [])
    cons    = topic_data.get("cons", [])
    sources = topic_data.get("sources", [])

    summary_items = "".join(
        f'<li style="margin-bottom:6px;">{s}</li>' for s in summary if s
    )
    pros_items = "".join(
        f'<li style="margin-bottom:4px;">{p}</li>' for p in pros
    )
    cons_items = "".join(
        f'<li style="margin-bottom:4px;">{c}</li>' for c in cons
    )
    source_links = "".join(
        f'<a href="{s["url"]}" style="display:block; color:{accent}; '
        f'text-decoration:none; font-size:0.82em; margin-bottom:4px; '
        f'word-break:break-all;">▶ {s["title"]}</a>'
        for s in sources
    )

    pros_block = f"""
        <div style="flex:1; background:#f0faf4; border-radius:8px; padding:12px;">
          <div style="font-weight:700; color:#27AE60; margin-bottom:8px;">✅ 장점</div>
          <ul style="margin:0; padding-left:18px; color:#444; font-size:0.88em;">{pros_items}</ul>
        </div>""" if pros_items else ""

    cons_block = f"""
        <div style="flex:1; background:#fdf0f0; border-radius:8px; padding:12px;">
          <div style="font-weight:700; color:#E74C3C; margin-bottom:8px;">⚠️ 주의점</div>
          <ul style="margin:0; padding-left:18px; color:#444; font-size:0.88em;">{cons_items}</ul>
        </div>""" if cons_items else ""

    return f"""
    <div style="background:#fff; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.08);
                margin-bottom:24px; overflow:hidden; border-top:4px solid {accent};">
      <!-- 주제 헤더 -->
      <div style="padding:20px 24px 12px;">
        <div style="font-size:1.05em; font-weight:800; color:#1a1a1a; margin-bottom:12px;">{topic}</div>
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
        <!-- 장단점 -->
        <div style="display:flex; gap:12px; flex-wrap:wrap;">
          {pros_block}
          {cons_block}
        </div>
      </div>
      <!-- 출처 -->
      <div style="background:#f8f9fa; padding:12px 24px; border-top:1px solid #eee;">
        <div style="font-size:0.78em; color:#888; font-weight:600;
                    text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px;">
          🔗 출처 영상
        </div>
        {source_links}
      </div>
    </div>"""


def _format_html(newsletter: Dict[str, Any]) -> str:
    """뉴스레터 딕셔너리 → 카드형 HTML 이메일 본문"""
    subject      = newsletter.get("subject", "오늘의 유튜브 브리핑 🎬")
    intent_type  = newsletter.get("intent_type", "지식형")
    topics       = newsletter.get("topics", [])

    accent       = _INTENT_COLOR.get(intent_type, "#4A90D9")
    intent_label = _INTENT_LABEL.get(intent_type, "")

    cards = "".join(_build_topic_card(t, accent) for t in topics)

    return f"""<!DOCTYPE html>
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
</html>"""


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
        print("[email] RESEND_API_KEY 없음 — 발송 스킵")
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
        print(f"[email] 발송 성공 → {user_email} | id={response.get('id', '-')}")
        return {"success": True}

    except Exception as e:
        print(f"[email] 발송 오류: {e}")
        return {"success": False}
