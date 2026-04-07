# backend/delivery/kakao.py
"""
카카오 친구톡 발송

전제 조건:
- 카카오 디벨로퍼스 앱 등록 (https://developers.kakao.com)
- 카카오 비즈 채널 개설 + 앱 연결
- 수신자가 해당 채널을 카카오톡에서 친구 추가한 상태여야 발송 가능

사용 API:
POST https://kapi.kakao.com/v1/api/talk/friends/message/default/send
헤더: Authorization: Bearer {카카오_액세스_토큰}
"""

import os
import requests
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

KAKAO_ACCESS_TOKEN = os.getenv("KAKAO_ACCESS_TOKEN")


def _format_message(newsletter: Dict[str, Any]) -> str:
    """
    뉴스레터 딕셔너리 → 카카오톡 텍스트 메시지 포맷
    카카오톡 텍스트는 최대 200자 제한이므로 간결하게 구성
    """
    lines = [newsletter.get("subject", "오늘의 유튜브 브리핑 🎬"), ""]

    for topic_data in newsletter.get("topics", []):
        topic = topic_data.get("topic", "")
        summary = topic_data.get("summary", [])
        sources = topic_data.get("sources", [])

        lines.append(f"📌 {topic}")

        # 요약 첫 줄만 포함 (카카오톡 길이 제한)
        if summary and summary[0]:
            lines.append(f"  {summary[0]}")

        # 출처 첫 번째 링크만 포함
        if sources:
            lines.append(f"  🔗 {sources[0]['url']}")

        lines.append("")

    return "\n".join(lines)


def send_kakao(
    kakao_uuid: str,
    newsletter: Dict[str, Any],
) -> Dict[str, Any]:
    """
    카카오 친구톡 발송

    INPUT:
      - kakao_uuid (str)    — 카카오 로그인 시 발급받은 사용자 식별자
      - newsletter (Dict)   — newsletter_ai 출력값

    OUTPUT:
      - success    (bool)
      - message_id (str)
    """
    if not KAKAO_ACCESS_TOKEN:
        print("[kakao] KAKAO_ACCESS_TOKEN 없음 — 발송 스킵")
        return {"success": False, "message_id": None}

    message_text = _format_message(newsletter)

    payload = {
        "receiver_uuids": f'["{kakao_uuid}"]',
        "template_object": {
            "object_type": "text",
            "text": message_text,
            "link": {
                "web_url": os.getenv("FRONTEND_URL", "http://localhost:8000"),
            },
        },
    }

    try:
        response = requests.post(
            "https://kapi.kakao.com/v1/api/talk/friends/message/default/send",
            headers={
                "Authorization": f"Bearer {KAKAO_ACCESS_TOKEN}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data=payload,
            timeout=10,
        )
        result = response.json()

        if response.status_code == 200:
            print(f"[kakao] 발송 성공 — uuid: {kakao_uuid}")
            return {
                "success":    True,
                "message_id": str(result.get("successful_receiver_uuids", [""])[0]),
            }
        else:
            print(f"[kakao] 발송 실패 — {result}")
            return {"success": False, "message_id": None}

    except Exception as e:
        print(f"[kakao] 발송 오류: {e}")
        return {"success": False, "message_id": None}