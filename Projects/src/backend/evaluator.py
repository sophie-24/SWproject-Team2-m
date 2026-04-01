import os
import json
import re
from typing import Dict, Any, List
from dotenv import load_dotenv
from google import genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

load_dotenv()

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception(lambda e: "429" in str(e)),
)
def _call_gemini(prompt: str) -> str:
    return _client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config={"temperature": 0},
    ).text

QUALITY_CRITERIA = ["relevance", "completeness", "accuracy", "clarity"]


def _parse_json(text: str) -> dict:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {}


def score_analysis(query: str, analysis: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """분석 결과를 4개 지표로 0~10점 채점합니다 (LLM-as-Judge)."""
    transcript_sample = " ".join(c["text"] for c in chunks)[:3000]

    prompt = f"""아래 분석 결과를 4가지 기준으로 각각 0~10점 평가하세요.
반드시 JSON 형식으로만 응답하세요.

기준:
- relevance: 사용자 질문에 대한 답변 관련성
- completeness: [1]핵심요약 [2]주요정보 [3]쟁점분석 [4]결론 구조 충족도
- accuracy: 원본 자막 내용과의 사실 일치도
- clarity: 문장의 명확성과 가독성

질문: {query}
원본 자막 일부: {transcript_sample}
분석 결과: {analysis[:3000]}

응답 형식:
{{"relevance": 0, "completeness": 0, "accuracy": 0, "clarity": 0, "reason": "한 줄 평"}}"""

    response = _client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config={"temperature": 0},
    )

    scores = _parse_json(response.text)
    if scores:
        scores["total"] = round(
            sum(scores.get(k, 0) for k in QUALITY_CRITERIA) / len(QUALITY_CRITERIA), 2
        )
    return scores


def score_ad_detection(ad_score: int, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """광고 탐지 점수를 독립적인 2차 검증으로 평가합니다."""
    full_text = " ".join(c["text"] for c in chunks)[:6000]

    prompt = f"""다음 자막에서 광고/홍보성 문장의 비율을 분석하세요.
반드시 JSON 형식으로만 응답하세요.

자막: {full_text}

응답 형식:
{{"reference_score": 0, "ad_phrases_found": [], "confidence": "high"}}
- reference_score: 광고성 정도 0~100
- ad_phrases_found: 광고로 의심되는 문장 최대 3개 리스트
- confidence: 판단 신뢰도 (high / medium / low)"""

    response = _client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config={"temperature": 0},
    )

    result = _parse_json(response.text)
    if result:
        ref = result.get("reference_score", 0)
        result["model_score"] = ad_score
        result["score_diff"] = abs(ad_score - ref)
        result["agreement"] = result["score_diff"] <= 20
    return result
