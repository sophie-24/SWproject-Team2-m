"""
format_ai -- newsletter format rules (utility module, not an agent)

Gemini를 호출하지 않는 순수 데이터 모듈입니다.
intent_ai.classify_intent()가 이 맵을 내부에서 직접 참조합니다.
orchestrator에서 별도로 호출하지 않습니다.
"""
from typing import Dict

FORMAT_MAP: Dict[str, Dict[str, str]] = {
    "유희형": {
        "tone": (
            "친근하고 가벼운 말투로 작성하세요. "
            "이모지를 적절히 활용하고, 딱딱한 표현은 피하세요. "
            "흥미를 유발하는 표현을 사용하세요."
        ),
        "structure": (
            "핵심 내용을 짧고 임팩트 있게 전달하세요. "
            "장단점보다는 '재밌는 포인트'와 '놓치면 아쉬운 것'으로 구성하세요."
        ),
        "length": "short",
    },
    "지식형": {
        "tone": (
            "정확하고 신뢰감 있는 문체로 작성하세요. "
            "전문 용어는 간단히 풀어서 설명하고, 근거를 중시하세요."
        ),
        "structure": (
            "배경 → 핵심 내용 → 시사점 순서로 구성하세요. "
            "공통 사실과 쟁점을 모두 포함하고, 출처를 강조하세요."
        ),
        "length": "long",
    },
    "구매형": {
        "tone": (
            "실용적이고 객관적인 말투로 작성하세요. "
            "수치와 비교 표현을 활용하고, 결론을 앞에 배치하세요."
        ),
        "structure": (
            "장점과 단점을 명확히 대비해서 작성하세요. "
            "'이런 사람에게 추천' 문구를 포함하고, 광고 영상은 반드시 명시하세요."
        ),
        "length": "long",
    },
}

DEFAULT_FORMAT = FORMAT_MAP["지식형"]
