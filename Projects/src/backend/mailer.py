# Gmail SMTP를 통한 HTML 뉴스레터 이메일 발송
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
    if not topics:
        return ""
    pills = "".join(
        f'<td style="padding:0 10px 10px 0;">'
        f'<span style="display:inline-block;background:#f5f7fa;border:1.5px solid #e4e8ed;'
        f'border-radius:9999px;padding:10px 24px;font-size:14px;color:#2d3748;'
        f'font-weight:500;white-space:nowrap;font-family:{_FONT};">'
        f'{t.get("topic","")}</span></td>'
        for t in topics if t.get("topic")
    )
    return (
        f'<table cellpadding="0" cellspacing="0" style="margin-bottom:0;">'
        f'<tr style="flex-wrap:wrap;">{pills}</tr></table>'
    )


def _inline_source_tag(source: Dict[str, Any]) -> str:
    channel = source.get("channel_title", "")
    url     = source.get("url", "#")
    if not channel:
        return ""
    yt_icon = (
        '<img src="https://www.youtube.com/favicon.ico" width="10" height="10" '
        'alt="YouTube" style="vertical-align:middle;margin-right:3px;">'
    )
    return (
        f'<a href="{url}" target="_blank" '
        f'style="display:inline-flex;align-items:center;font-size:11px;color:#64748b;'
        f'background:#f1f5f9;border:1px solid #e2e8f0;border-radius:4px;'
        f'padding:2px 8px;margin-left:6px;text-decoration:none;'
        f'vertical-align:middle;white-space:nowrap;font-family:{_FONT};">'
        f'{yt_icon}{channel}</a>'
    )


def _controversy_bullets(controversies: List[str], sources: List[Dict[str, Any]]) -> str:
    if not controversies:
        return ""
    items = []
    for i, c in enumerate(controversies):
        if not c:
            continue
        tag_html = _inline_source_tag(sources[i % len(sources)]) if sources else ""
        items.append(
            f'<li style="margin-bottom:12px;font-size:16px;color:#1e293b;'
            f'line-height:1.8;font-family:{_FONT};">'
            f'{c}{tag_html}'
            f'</li>'
        )
    return (
        f'<ul style="margin:0;padding-left:20px;list-style-type:disc;">'
        + "".join(items)
        + '</ul>'
    )


def _source_video_cards(sources: List[Dict[str, Any]]) -> str:
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
            f'<img src="{thumbnail_url}" width="220" height="124" '
            f'style="width:220px;height:124px;object-fit:cover;border-radius:10px;display:block;" '
            f'alt="" /></a>'
        ) if thumbnail_url else (
            f'<a href="{url}" target="_blank" '
            f'style="display:block;width:220px;height:124px;background:#e2e8f0;border-radius:10px;"></a>'
        )

        insight_html = (
            f'<p style="margin:8px 0 0;font-size:14px;color:#64748b;line-height:1.7;'
            f'font-family:{_FONT};">{summary}</p>'
        ) if summary else ""

        channel_tag = (
            f'<span style="display:inline-block;background:#eff6ff;border-radius:9999px;'
            f'padding:4px 12px;font-size:11px;color:#3b82f6;font-weight:600;'
            f'letter-spacing:0.3px;">{channel_title}</span>'
        ) if channel_title else ""

        cards.append(
            f'<table cellpadding="0" cellspacing="0" width="100%"'
            f' style="background:#f8fafc;border-radius:14px;margin-bottom:14px;'
            f'border-collapse:separate;border:1.5px solid #eef0f3;">'
            f'<tr>'
            f'<td style="padding:18px;vertical-align:middle;width:220px;">{thumb_html}</td>'
            f'<td style="padding:18px 20px 18px 4px;vertical-align:middle;">'
            f'<a href="{url}" target="_blank" style="text-decoration:none;">'
            f'<p style="margin:0 0 8px;font-size:17px;line-height:1.5;color:#1a202c;'
            f'font-weight:600;font-family:{_FONT};">{title}</p></a>'
            f'{insight_html}'
            f'<div style="margin-top:16px;">{channel_tag}</div>'
            f'</td>'
            f'</tr>'
            f'</table>'
        )
    return "".join(cards)


def _build_topic_section(topic_data: Dict[str, Any], unsubscribe_url: str = "") -> str:
    topic         = topic_data.get("topic", "")
    summary       = topic_data.get("summary", [])
    pros          = topic_data.get("pros", [])
    cons          = topic_data.get("cons", [])
    common_facts  = topic_data.get("common_facts", [])
    controversies = topic_data.get("controversies", [])
    sources       = topic_data.get("sources", [])

    left_items = [s for s in summary if s] or [p for p in pros if p] or [f for f in common_facts if f]
    left_text  = " ".join(left_items) if left_items else "분석 중입니다."

    right_items  = [c for c in controversies if c] or [c for c in cons if c]
    sources_html = _source_video_cards(sources)

    unsubscribe_html = (
        f'<p style="text-align:right;margin:8px 0 0;">'
        f'<a href="{unsubscribe_url}" style="font-size:12px;color:#cbd5e0;text-decoration:none;">'
        f'이 주제 구독 취소</a></p>'
    ) if unsubscribe_url else ""

    right_col_html = (
        f'<td style="width:46%;vertical-align:top;padding-left:28px;'
        f'border-left:2px solid #f1f5f9;">'
        f'<p style="margin:0 0 12px;font-size:11px;color:#3b82f6;letter-spacing:1.5px;'
        f'text-transform:uppercase;font-weight:700;font-family:{_FONT};">주요 쟁점</p>'
        + _controversy_bullets(right_items, sources)
        + f'</td>'
    ) if right_items else '<td style="width:46%;"></td>'

    return (
        f'<table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:80px;">'
        f'<tr><td>'

        # 토픽 헤딩
        f'<table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:28px;">'
        f'<tr>'
        f'<td style="padding-bottom:16px;border-bottom:2px solid #ff0000;">'
        f'<span style="font-size:11px;color:#ff0000;letter-spacing:2px;'
        f'text-transform:uppercase;font-weight:700;font-family:{_FONT};">TOPIC</span><br>'
        f'<span style="font-size:32px;font-weight:800;color:#0f172a;letter-spacing:-1px;'
        f'line-height:1.25;font-family:{_FONT};">{topic}</span>'
        f'</td>'
        f'</tr>'
        f'</table>'

        # 2열 콘텐츠
        f'<table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:36px;">'
        f'<tr>'
        f'<td style="width:54%;vertical-align:top;padding-right:28px;">'
        f'<p style="margin:0 0 12px;font-size:11px;color:#ff0000;letter-spacing:1.5px;'
        f'text-transform:uppercase;font-weight:700;font-family:{_FONT};">핵심 내용</p>'
        f'<p style="margin:0;font-size:16px;color:#1e293b;line-height:1.85;'
        f'font-family:{_FONT};">{left_text}</p>'
        f'</td>'
        f'{right_col_html}'
        f'</tr>'
        f'</table>'

        # 주요 소스
        f'<p style="margin:0 0 18px;font-size:11px;color:#94a3b8;letter-spacing:2px;'
        f'text-transform:uppercase;font-weight:700;font-family:{_FONT};'
        f'padding-top:28px;border-top:1px solid #f1f5f9;">참고 영상</p>'
        f'{sources_html}'
        f'{unsubscribe_html}'

        f'</td></tr>'
        f'</table>'
    )


def _format_html(newsletter: Dict[str, Any], recipient_email: str = "") -> str:
    subject  = newsletter.get("subject", "오늘의 Tubify 브리핑")
    topics   = newsletter.get("topics", [])

    topic_names = [t.get("topic", "") for t in topics if t.get("topic")]
    if len(topic_names) == 0:
        header_title = "오늘의 추천 영상<br>도착했어요"
    elif len(topic_names) == 1:
        header_title = f"오늘의 <span style='color:#ff0000;'>{topic_names[0]}</span><br>영상 도착했어요"
    elif len(topic_names) == 2:
        header_title = f"오늘의 <span style='color:#ff0000;'>{topic_names[0]}</span>,<br><span style='color:#ff0000;'>{topic_names[1]}</span> 영상 도착했어요"
    else:
        rest = f" 외 {len(topic_names) - 2}개"
        header_title = f"오늘의 <span style='color:#ff0000;'>{topic_names[0]}</span>, <span style='color:#ff0000;'>{topic_names[1]}</span>{rest}<br>영상 도착했어요"

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
        f'<span style="color:#94a3b8;font-size:13px;font-family:{_FONT};">'
        f'수신: <strong style="color:#475569;">{recipient_email}</strong></span>'
    ) if recipient_email else ""

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#eef1f5;font-family:{_FONT};">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#eef1f5;">
    <tr><td align="center" style="padding:48px 16px 64px;">

      <!-- 상단 로고 -->
      <table width="660" cellpadding="0" cellspacing="0" style="max-width:660px;width:100%;margin-bottom:20px;">
        <tr>
          <td style="padding:0 4px;">
            <span style="font-size:22px;font-weight:900;color:#ff0000;letter-spacing:-0.5px;
                         font-family:{_FONT};">Tubify</span>
            &nbsp;
            <span style="font-size:13px;color:#94a3b8;font-family:{_FONT};">Daily Brief</span>
          </td>
          <td style="text-align:right;vertical-align:middle;">
            {recipient_html}
          </td>
        </tr>
      </table>

      <!-- 메인 카드 -->
      <table width="660" cellpadding="0" cellspacing="0"
             style="max-width:660px;width:100%;background:#ffffff;border-radius:20px;
                    box-shadow:0 4px 24px rgba(0,0,0,0.07);border-collapse:separate;
                    border-spacing:0;">

        <!-- ── 헤더 ── -->
        <tr><td style="padding:52px 56px 32px;border-bottom:1px solid #f1f5f9;">
          <p style="margin:0 0 6px;font-size:12px;color:#ff0000;letter-spacing:2px;
                    text-transform:uppercase;font-weight:700;font-family:{_FONT};">
            관심사 기반 영상 브리핑
          </p>
          <p style="margin:0 0 32px;font-size:34px;font-weight:800;color:#0f172a;
                    letter-spacing:-1px;line-height:1.35;font-family:{_FONT};">
            {header_title}
          </p>
        </td></tr>

        <!-- ── 본문 ── -->
        <tr><td style="padding:40px 56px 32px;">
          {articles_html}
        </td></tr>

        <!-- ── 푸터 ── -->
        <tr><td style="padding:36px 56px 44px;border-top:1px solid #f1f5f9;
                        border-radius:0 0 20px 20px;background:#fafbfc;">
          <table cellpadding="0" cellspacing="0" width="100%">
            <tr>
              <td style="vertical-align:middle;">
                <span style="font-size:18px;font-weight:900;color:#ff0000;
                             font-family:{_FONT};">Tubify</span>
              </td>
              <td style="text-align:right;vertical-align:middle;">
                <a href="{BACKEND_URL}/mypage.html"
                   style="display:inline-block;background:#f1f5f9;color:#475569;
                          font-size:13px;text-decoration:none;padding:10px 22px;
                          border-radius:8px;margin-left:8px;font-family:{_FONT};">설정 관리</a>
                <a href="{BACKEND_URL}/mypage.html"
                   style="display:inline-block;background:#f1f5f9;color:#475569;
                          font-size:13px;text-decoration:none;padding:10px 22px;
                          border-radius:8px;margin-left:8px;font-family:{_FONT};">구독 해지</a>
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
