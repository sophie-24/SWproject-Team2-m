# backend/delivery/email.py
"""
이메일 뉴스레터 발송
SMTP 방식 사용 (Gmail 기준)

.env 필요 항목:
  EMAIL_SENDER=your@gmail.com
  EMAIL_PASSWORD=앱_비밀번호   # 구글 앱 비밀번호 (2단계 인증 필요)
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

EMAIL_SENDER   = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587


def _format_html(newsletter: Dict[str, Any]) -> str:
    """뉴스레터 딕셔너리 → HTML 이메일 본문"""
    subject = newsletter.get("subject", "오늘의 유튜브 브리핑 🎬")
    topics  = newsletter.get("topics", [])

    topic_html = ""
    for topic_data in topics:
        topic   = topic_data.get("topic", "")
        summary = topic_data.get("summary", [])
        pros    = topic_data.get("pros", [])
        cons    = topic_data.get("cons", [])
        sources = topic_data.get("sources", [])

        summary_html = "".join(f"<li>{s}</li>" for s in summary if s)
        pros_html    = "".join(f"<li>{p}</li>" for p in pros)
        cons_html    = "".join(f"<li>{c}</li>" for c in cons)
        sources_html = "".join(
            f'<li><a href="{s["url"]}">{s["title"]}</a></li>'
            for s in sources
        )

        topic_html += f"""
        <div style="margin-bottom:32px; border-left:4px solid #FF0000; padding-left:16px;">
            <h2 style="color:#333;">{topic}</h2>
            <h3>📋 요약</h3>
            <ul>{summary_html}</ul>
            <h3>✅ 장점</h3>
            <ul>{pros_html}</ul>
            <h3>⚠️ 단점</h3>
            <ul>{cons_html}</ul>
            <h3>🔗 출처</h3>
            <ul>{sources_html}</ul>
        </div>
        """

    return f"""
    <html>
    <body style="font-family:sans-serif; max-width:600px; margin:auto; padding:24px;">
        <h1 style="color:#FF0000;">{subject}</h1>
        {topic_html}
        <hr>
        <p style="color:#999; font-size:12px;">
            TechVisibility — 유튜브 큐레이션 뉴스레터
        </p>
    </body>
    </html>
    """


def send_email(
    user_email: str,
    newsletter: Dict[str, Any],
) -> Dict[str, bool]:
    """
    이메일 뉴스레터 발송

    INPUT:
      - user_email (str)  — 수신자 이메일
      - newsletter (Dict) — newsletter_ai 출력값

    OUTPUT:
      - success (bool)
    """
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("[email] EMAIL_SENDER 또는 EMAIL_PASSWORD 없음 — 발송 스킵")
        return {"success": False}

    subject  = newsletter.get("subject", "오늘의 유튜브 브리핑 🎬")
    html_body = _format_html(newsletter)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = user_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.sendmail(EMAIL_SENDER, user_email, msg.as_string())

        print(f"[email] 발송 성공 → {user_email}")
        return {"success": True}

    except Exception as e:
        print(f"[email] 발송 오류: {e}")
        return {"success": False}