# Gmail SMTP를 통한 HTML 뉴스레터 이메일 발송 — Figma 디자인 기반
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, List
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()
from logger import get_logger
logger = get_logger(__name__)

GMAIL_USER         = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
BACKEND_URL        = os.getenv("FRONTEND_URL", "http://localhost:8000")

_FONT = "'Apple SD Gothic Neo','Noto Sans KR','Segoe UI',sans-serif"


def _keyword_pills(topics: List[Dict[str, Any]]) -> str:
    """토픽 목록 → 키워드 필 버튼 HTML."""
    if not topics:
        return ""
    pills = "".join(
        f'<td style="padding:0 8px 0 0;">'
        f'<span style="display:inline-block;background:#ffffff;border:1px solid #eceef0;'
        f'border-radius:9999px;padding:9px 21px;font-size:14px;color:#191c1e;'
        f'white-space:nowrap;font-family:{_FONT};">'
        f'{t.get("topic","")}</span></td>'
        for t in topics if t.get("topic")
    )
    return (
        f'<table cellpadding="0" cellspacing="0" style="margin-bottom:48px;">'
        f'<tr>{pills}</tr></table>'
    )


def _source_video_cards(sources: List[Dict[str, Any]]) -> str:
    """출처 영상 목록 → 세로 스택 카드 HTML."""
    if not sources:
        return ""
    cards = []
    for s in sources:
        title         = s.get("title", "")
        url           = s.get("url", "#")
        thumbnail_url = s.get("thumbnail_url", "")
        channel_title = s.get("channel_title", "")
        summary       = s.get("summary", "")

        thumb_html = (
            f'<a href="{url}" target="_blank" style="display:block;text-decoration:none;">'
            f'<img src="{thumbnail_url}" width="210" height="118" '
            f'style="width:210px;height:118px;object-fit:cover;border-radius:8px;display:block;" '
            f'alt="" /></a>'
        ) if thumbnail_url else (
            f'<a href="{url}" target="_blank" '
            f'style="display:block;width:210px;height:118px;background:#e2e8f0;border-radius:8px;"></a>'
        )

        insight_html = (
            f'<p style="margin:6px 0 0;font-size:15px;color:#515f74;line-height:1.5;'
            f'font-family:{_FONT};">'
            f'<span style="color:#603e39;">핵심 통찰:</span> {summary}</p>'
        ) if summary else ""

        channel_tag = (
            f'<span style="display:inline-block;background:#d5e3fc;border-radius:9999px;'
            f'padding:2px 8px;font-size:10px;color:#57657a;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.5px;">{channel_title}</span>'
        ) if channel_title else ""

        cards.append(
            f'<table cellpadding="0" cellspacing="0" width="100%"'
            f' style="background:#f2f4f6;border-radius:12px;margin-bottom:16px;border-collapse:separate;">'
            f'<tr>'
            f'<td style="padding:16px;vertical-align:middle;width:210px;">{thumb_html}</td>'
            f'<td style="padding:16px;vertical-align:middle;">'
            f'<a href="{url}" target="_blank" style="text-decoration:none;">'
            f'<p style="margin:0 0 6px;font-size:19px;line-height:1.4;color:#191c1e;'
            f'font-family:{_FONT};">{title}</p></a>'
            f'{insight_html}'
            f'<div style="margin-top:14px;">{channel_tag}</div>'
            f'</td>'
            f'</tr>'
            f'</table>'
        )
    return "".join(cards)


def _build_topic_section(topic_data: Dict[str, Any], unsubscribe_url: str = "") -> str:
    """토픽 1개 → Figma 기반 섹션 HTML."""
    topic         = topic_data.get("topic", "")
    summary       = topic_data.get("summary", [])
    pros          = topic_data.get("pros", [])
    cons          = topic_data.get("cons", [])
    common_facts  = topic_data.get("common_facts", [])
    controversies = topic_data.get("controversies", [])
    sources       = topic_data.get("sources", [])

    left_items = [s for s in summary if s] or [p for p in pros if p] or [f for f in common_facts if f]
    left_text  = " ".join(left_items) if left_items else "분석 중입니다."

    right_items = [c for c in controversies if c] or [c for c in cons if c]
    right_text  = " ".join(right_items) if right_items else ""

    sources_html = _source_video_cards(sources)

    unsubscribe_html = (
        f'<p style="text-align:right;margin:6px 0 0;">'
        f'<a href="{unsubscribe_url}" style="font-size:12px;color:#bbb;text-decoration:none;">'
        f'이 주제 구독 취소</a></p>'
    ) if unsubscribe_url else ""

    right_col_html = (
        f'<td style="width:50%;vertical-align:top;padding-left:20px;">'
        f'<p style="margin:0 0 10px;font-size:12px;color:#0059ba;letter-spacing:1.2px;'
        f'text-transform:uppercase;font-weight:600;font-family:{_FONT};">&#8593; 주요 쟁점</p>'
        f'<p style="margin:0;font-size:17px;color:#191c1e;line-height:1.65;'
        f'font-family:{_FONT};">{right_text}</p>'
        f'</td>'
    ) if right_text else '<td style="width:50%;"></td>'

    return (
        f'<table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:64px;">'
        f'<tr><td>'

        # 헤딩 행
        f'<table cellpadding="0" cellspacing="0" style="margin-bottom:32px;">'
        f'<tr>'
        f'<td style="width:48px;padding-right:16px;vertical-align:middle;">'
        f'<div style="width:48px;height:6px;border-radius:9999px;background:#ff0000;"></div>'
        f'</td>'
        f'<td style="vertical-align:middle;">'
        f'<span style="font-size:28px;font-weight:700;color:#191c1e;letter-spacing:-0.75px;'
        f'line-height:1.3;font-family:{_FONT};">{topic}</span>'
        f'</td>'
        f'</tr>'
        f'</table>'

        # 2열 콘텐츠
        f'<table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:32px;">'
        f'<tr>'
        f'<td style="width:50%;vertical-align:top;padding-right:20px;">'
        f'<p style="margin:0 0 10px;font-size:12px;color:#ff0000;letter-spacing:1.2px;'
        f'text-transform:uppercase;font-weight:600;font-family:{_FONT};">&#9650; 핵심 내용</p>'
        f'<p style="margin:0;font-size:17px;color:#191c1e;line-height:1.65;'
        f'font-family:{_FONT};">{left_text}</p>'
        f'</td>'
        f'{right_col_html}'
        f'</tr>'
        f'</table>'

        # 주요 소스
        f'<p style="margin:0 0 16px;font-size:13px;color:#515f74;letter-spacing:1.4px;'
        f'text-transform:uppercase;border-top:1px solid #eceef0;padding-top:16px;'
        f'font-family:{_FONT};">주요 소스</p>'
        f'{sources_html}'
        f'{unsubscribe_html}'

        f'</td></tr>'
        f'</table>'
    )


def _format_html(newsletter: Dict[str, Any], recipient_email: str = "") -> str:
    """뉴스레터 딕셔너리 → Figma 기반 HTML 이메일 본문."""
    subject  = newsletter.get("subject", "오늘의 Tubify 브리핑")
    topics   = newsletter.get("topics", [])

    pills_html    = _keyword_pills(topics)
    articles_html = "".join(
        _build_topic_section(
            t,
            unsubscribe_url=(
                f"{BACKEND_URL}/interests/unsubscribe-confirm"
                f"?topic={quote(t.get('topic', ''), safe='')}"
            ),
        )
        for t in topics
    )

    recipient_html = (
        f'&nbsp;&nbsp;'
        f'<span style="color:#515f74;">받는사람: </span>'
        f'<span style="color:#191c1e;font-weight:600;">{recipient_email}</span>'
    ) if recipient_email else ""

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#f7f9fb;font-family:{_FONT};">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f7f9fb;">
    <tr><td align="center" style="padding:48px 16px;">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;
                    box-shadow:0 2px 8px rgba(0,0,0,0.05);border-collapse:separate;
                    border-spacing:0;">

        <!-- ── 헤더 ── -->
        <tr><td style="background:#f2f4f6;border-radius:12px 12px 0 0;
                        padding:32px;border-bottom:1px solid #eceef0;">
          <p style="margin:0 0 16px;font-size:26px;font-weight:700;color:#191c1e;
                    letter-spacing:-0.75px;line-height:1.3;font-family:{_FONT};">
            관심사 기반 추천 영상 요약 도착했습니다
          </p>
          <table cellpadding="0" cellspacing="0">
            <tr>
              <td style="padding-right:14px;vertical-align:middle;">
                <span style="display:inline-block;background:#ff0000;color:#ffffff;
                             font-size:12px;padding:2px 10px;border-radius:8px;
                             font-family:{_FONT};">관심사 기반 요약</span>
              </td>
              <td style="vertical-align:middle;">
                <span style="font-size:13px;font-family:{_FONT};">
                  <span style="color:#515f74;">보낸사람: </span>
                  <span style="color:#191c1e;font-weight:600;">curator@tubify.com</span>
                </span>
                {recipient_html}
              </td>
            </tr>
          </table>
        </td></tr>

        <!-- ── 본문 ── -->
        <tr><td style="padding:48px 40px 24px;">
          {pills_html}
          {articles_html}
        </td></tr>

        <!-- ── 푸터 ── -->
        <tr><td style="padding:32px;border-top:1px solid #eceef0;text-align:center;
                        border-radius:0 0 12px 12px;">
          <p style="margin:0 0 20px;font-size:24px;font-weight:900;color:#ff0000;
                    font-family:{_FONT};">Tubify</p>
          <table cellpadding="0" cellspacing="0" style="margin:0 auto;">
            <tr>
              <td style="padding-right:10px;">
                <a href="{BACKEND_URL}/mypage.html"
                   style="display:inline-block;background:#e6e8ea;color:#191c1e;
                          font-size:14px;text-decoration:none;padding:11px 28px;
                          border-radius:8px;font-family:{_FONT};">설정 관리</a>
              </td>
              <td>
                <a href="{BACKEND_URL}/mypage.html"
                   style="display:inline-block;background:#e6e8ea;color:#191c1e;
                          font-size:14px;text-decoration:none;padding:11px 28px;
                          border-radius:8px;font-family:{_FONT};">구독 해지</a>
              </td>
            </tr>
          </table>
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
    Gmail SMTP를 통한 뉴스레터 발송

    INPUT:
      - user_email (str)  — 수신자 이메일
      - newsletter (Dict) — newsletter_ai 출력값

    OUTPUT:
      - {"success": bool}

    ENV:
      - GMAIL_USER         — 발신 Gmail 주소
      - GMAIL_APP_PASSWORD — Google 앱 비밀번호 (16자리)
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        logger.warning("[email] GMAIL_USER 또는 GMAIL_APP_PASSWORD 없음 — 발송 스킵")
        return {"success": False}

    subject   = newsletter.get("subject", "오늘의 Tubify 브리핑")
    html_body = _format_html(newsletter, recipient_email=user_email)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Tubify <{GMAIL_USER}>"
    msg["To"]      = user_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.sendmail(GMAIL_USER, user_email, msg.as_bytes())
        logger.info(f"[email] 발송 성공 → {user_email}")
        return {"success": True}

    except Exception as e:
        logger.error(f"[email] 발송 오류: {e}")
        return {"success": False}
