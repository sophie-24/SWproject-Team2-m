# Resend API를 통한 HTML 뉴스레터 이메일 발송 — 의도별 카드 레이아웃(썸네일·쟁점배지·채널명)
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


_HEADER_TITLE = {
    "search":   "방금 찾은 내용, 한눈에 정리해드립니다",
    "interest": "관심사 기반 추천 영상 요약 도착했습니다",
}
_HEADER_BADGE = {
    "search":   "검색어 기반 요약",
    "interest": "관심사 기반 요약",
}


def _keyword_pills(topics: List[Dict[str, Any]]) -> str:
    """토픽 목록 → 키워드 필터 필 HTML"""
    if not topics:
        return ""
    pills = "".join(
        f'<td style="padding:0 6px 0 0;">'
        f'<span style="display:inline-block; background:#ffffff; border:1px solid #eceef0; '
        f'border-radius:9999px; padding:7px 18px; font-size:13px; color:#191c1e; '
        f'white-space:nowrap;">{t.get("topic","")}</span></td>'
        for t in topics if t.get("topic")
    )
    return f'<table cellpadding="0" cellspacing="0" style="margin-bottom:48px;"><tr>{pills}</tr></table>'


def _source_cards(sources: List[Dict[str, Any]]) -> str:
    """출처 영상 목록 → Figma 스타일 카드 HTML (세로 스택)"""
    if not sources:
        return ""

    rows = []
    for s in sources[:4]:
        title         = s.get("title", "")
        url           = s.get("url", "#")
        channel_title = s.get("channel_title", "").upper()
        thumbnail_url = s.get("thumbnail_url", "")

        thumb_html = (
            f'<img src="{thumbnail_url}" alt="" width="126" height="71" '
            f'style="display:block; width:126px; height:71px; object-fit:cover; '
            f'border-radius:6px; border:0;">'
        ) if thumbnail_url else (
            f'<div style="width:126px; height:71px; background:#e2e8f0; border-radius:6px; '
            f'display:flex; align-items:center; justify-content:center;">'
            f'<span style="font-size:20px;">&#9654;</span></div>'
        )
        channel_badge = (
            f'<span style="display:inline-block; background:#d5e3fc; border-radius:9999px; '
            f'padding:2px 8px; font-size:10px; font-weight:600; color:#57657a; '
            f'letter-spacing:0.5px;">{channel_title}</span>'
        ) if channel_title else ""

        rows.append(f'''
        <tr>
          <td style="padding:0 0 12px 0;">
            <table cellpadding="0" cellspacing="0" width="100%"
                   style="background:#f2f4f6; border-radius:10px; overflow:hidden;">
              <tr>
                <td width="126" style="padding:14px 16px 14px 14px; vertical-align:middle;">
                  <a href="{url}" style="text-decoration:none;">{thumb_html}</a>
                </td>
                <td style="padding:14px 14px 14px 0; vertical-align:middle;">
                  <a href="{url}" style="text-decoration:none; font-size:17px; font-weight:400;
                     color:#191c1e; line-height:1.4; display:block; margin-bottom:6px;">{title}</a>
                  <div style="font-size:13px; color:#515f74; margin-bottom:10px;">
                    <span style="color:#603e39;">핵심 통찰: </span>
                  </div>
                  <div>{channel_badge}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>''')

    return f'<table cellpadding="0" cellspacing="0" width="100%">{"".join(rows)}</table>'


# intent_type별 섹션 라벨
_LEFT_LABEL = {
    "유희형": "&#9650; 화제 포인트",
    "구매형": "&#9650; 장점",
    "지식형": "&#9650; 핵심 인사이트",
}
_RIGHT_LABEL = {
    "유희형": "&#8593; 논란 및 쟁점",
    "구매형": "&#8593; 단점 및 주의사항",
    "지식형": "&#8593; 주요 관점",
}


def _build_topic_section(topic_data: Dict[str, Any], intent_type: str = "지식형") -> str:
    """주제 1개 → Figma 디자인 기반 섹션 HTML"""
    topic         = topic_data.get("topic", "")
    summary       = topic_data.get("summary", [])
    pros          = topic_data.get("pros", [])
    cons          = topic_data.get("cons", [])
    common_facts  = topic_data.get("common_facts", [])
    controversies = topic_data.get("controversies", [])
    sources       = topic_data.get("sources", [])

    left_label  = _LEFT_LABEL.get(intent_type, _LEFT_LABEL["지식형"])
    right_label = _RIGHT_LABEL.get(intent_type, _RIGHT_LABEL["지식형"])

    # 왼쪽: 요약 + 공통사실 + 장점
    left_items = [s for s in summary if s and "분석 가능한" not in s]
    if not left_items:
        left_items = [f for f in common_facts if f]
    if not left_items:
        left_items = [p for p in pros if p]
    left_text = " ".join(left_items) if left_items else "자막이 없는 영상으로 구성되어 요약을 생성하지 못했습니다. 아래 소스 영상을 직접 확인해보세요."

    # 오른쪽: 쟁점 + 단점
    right_items = [c for c in controversies if c]
    if not right_items:
        right_items = [c for c in cons if c]
    right_text = " ".join(right_items) if right_items else "영상 간 관점 차이를 분석하지 못했습니다."

    source_html = _source_cards(sources)

    return f'''
    <!-- 섹션: {topic} -->
    <table cellpadding="0" cellspacing="0" width="100%"
           style="margin-bottom:60px;">
      <!-- 섹션 헤딩 -->
      <tr>
        <td style="padding-bottom:28px;">
          <table cellpadding="0" cellspacing="0">
            <tr>
              <td width="48" style="padding-right:14px; vertical-align:middle;">
                <div style="width:48px; height:6px; border-radius:9999px;
                            background:linear-gradient(135deg,#ff0000 0%,#eb0000 100%);"></div>
              </td>
              <td style="vertical-align:middle;">
                <span style="font-size:26px; font-weight:700; color:#191c1e;
                             letter-spacing:-0.5px;">{topic}</span>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <!-- 2열 분석 -->
      <tr>
        <td style="padding-bottom:28px;">
          <table cellpadding="0" cellspacing="0" width="100%">
            <tr valign="top">
              <!-- 왼쪽 -->
              <td width="48%" style="padding-right:16px;">
                <div style="margin-bottom:10px;">
                  <span style="font-size:11px; font-weight:400; color:#ff0000;
                               letter-spacing:1.2px; text-transform:uppercase;">
                    {left_label}
                  </span>
                </div>
                <div style="font-size:16px; font-weight:400; color:#191c1e;
                            line-height:1.625;">{left_text}</div>
              </td>
              <!-- 오른쪽 -->
              <td width="48%" style="padding-left:16px;">
                <div style="margin-bottom:10px;">
                  <span style="font-size:11px; font-weight:400; color:#0059ba;
                               letter-spacing:1.2px; text-transform:uppercase;">
                    {right_label}
                  </span>
                </div>
                <div style="font-size:16px; font-weight:400; color:#191c1e;
                            line-height:1.625;">{right_text}</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <!-- 주요 소스 -->
      <tr>
        <td style="padding-top:10px;">
          <div style="font-size:12px; font-weight:400; color:#515f74;
                      letter-spacing:1.4px; text-transform:uppercase; margin-bottom:16px;">
            주요 소스
          </div>
          {source_html}
        </td>
      </tr>
    </table>'''


def _format_html(newsletter: Dict[str, Any], user_email: str = "",
                 newsletter_type: str = "search") -> str:
    """뉴스레터 딕셔너리 → Figma 디자인 기반 HTML 이메일"""
    import datetime
    subject     = newsletter.get("subject", "오늘의 유튜브 브리핑")
    topics      = newsletter.get("topics", [])
    intent_type = newsletter.get("intent_type", "지식형")
    now_str     = datetime.datetime.now().strftime("%Y년 %m월 %d일 %H:%M")

    header_title = _HEADER_TITLE.get(newsletter_type, _HEADER_TITLE["search"])
    header_badge = _HEADER_BADGE.get(newsletter_type, _HEADER_BADGE["search"])

    pills    = _keyword_pills(topics)
    sections = "".join(_build_topic_section(t, intent_type) for t in topics)

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0; padding:0; background:#f7f9fb;
             font-family:'Apple SD Gothic Neo','Noto Sans KR','Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f7f9fb;">
    <tr><td align="center" style="padding:40px 16px 60px;">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px; width:100%; background:#ffffff;
                    border-radius:12px; border:1px solid rgba(235,187,180,0.1);
                    box-shadow:0 2px 8px rgba(0,0,0,0.05); overflow:hidden;">

        <!-- 이메일 헤더 -->
        <tr>
          <td style="background:#f2f4f6; padding:28px 28px 24px;
                     border-bottom:1px solid rgba(235,187,180,0.1);">
            <!-- 제목 -->
            <div style="font-size:22px; font-weight:600; color:#191c1e;
                        letter-spacing:-0.5px; margin-bottom:12px; line-height:1.3;">
              {header_title}
            </div>
            <!-- 뱃지 + 메타 -->
            <table cellpadding="0" cellspacing="0">
              <tr valign="middle">
                <td style="padding-right:14px;">
                  <span style="display:inline-block; background:#ff0000; border-radius:6px;
                               padding:2px 10px; font-size:11px; color:#ffffff;
                               font-weight:400; white-space:nowrap;">
                    {header_badge}
                  </span>
                </td>
                <td>
                  <span style="font-size:13px; color:#515f74;">
                    보낸사람:&nbsp;<strong style="color:#191c1e;">curator@tubify.com</strong>
                    &nbsp;&nbsp;
                    받는사람:&nbsp;<strong style="color:#191c1e;">{user_email or "subscriber@reader.com"}</strong>
                    &nbsp;&nbsp;
                    일시:&nbsp;<span style="color:#191c1e;">{now_str}</span>
                  </span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- 이메일 본문 -->
        <tr>
          <td style="background:#ffffff; padding:40px 28px 20px;">
            <!-- 키워드 필터 필 -->
            {pills}
            <!-- 주제별 섹션 -->
            {sections}
          </td>
        </tr>

        <!-- 이메일 푸터 -->
        <tr>
          <td style="padding:48px 28px 36px; border-top:1px solid rgba(235,187,180,0.15);
                     text-align:center;">
            <div style="font-size:22px; font-weight:800; color:#ff0000;
                        margin-bottom:24px; letter-spacing:-0.3px;">Tubify</div>
            <table cellpadding="0" cellspacing="0" align="center">
              <tr>
                <td style="padding-right:10px;">
                  <a href="https://tubify.app/mypage" style="display:inline-block;
                     background:#e6e8ea; border-radius:8px; padding:10px 28px;
                     font-size:13px; color:#191c1e; text-decoration:none;
                     font-weight:400;">설정 관리</a>
                </td>
                <td>
                  <a href="https://tubify.app/unsubscribe" style="display:inline-block;
                     background:#e6e8ea; border-radius:8px; padding:10px 28px;
                     font-size:13px; color:#191c1e; text-decoration:none;
                     font-weight:400;">구독 해지</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>'''


def send_email(
    user_email: str,
    newsletter: Dict[str, Any],
    newsletter_type: str = "search",
) -> Dict[str, bool]:
    """
    Resend API를 통한 뉴스레터 발송

    INPUT:
      - user_email      (str)  — 수신자 이메일
      - newsletter      (Dict) — newsletter_ai 출력값
      - newsletter_type (str)  — "search" | "interest" (기본: "search")

    OUTPUT:
      - {"success": bool}

    ENV:
      - RESEND_API_KEY    — Resend API 키 (필수)
      - RESEND_FROM_EMAIL — 발신자 주소 (기본: curator@tubify.com)
    """
    if not RESEND_API_KEY:
        logger.warning("[email] RESEND_API_KEY 없음 — 발송 스킵")
        return {"success": False}

    subject   = newsletter.get("subject", "오늘의 유튜브 브리핑 🎬")
    html_body = _format_html(newsletter, user_email=user_email, newsletter_type=newsletter_type)

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
