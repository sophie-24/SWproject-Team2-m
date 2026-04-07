import os
from typing import List, Dict, Any
from dotenv import load_dotenv
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

load_dotenv()

genai.configure(api_key=os.environ["GEMINI_API_KEY"]) 
_model = genai.GenerativeModel("gemini-2.5-flash-lite")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=60),
)
def _call_gemini(prompt: str) -> str:
    response = _model.generate_content( 
        prompt,
        generation_config={"temperature": 0.3},
    )
    if response.text is None:                   
        finish = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        raise ValueError(f"Gemini 응답 없음 (finish_reason: {finish})")
    return response.text

_PROMPT_TEMPLATE = """
당신은 다양한 주제에 대해 깊이 있는 분석을 수행하는 전문가입니다.

사용자의 질문과 제공된 자막 데이터를 바탕으로 아래 형식으로 답변하세요:

[1] 핵심 요약
- 전체 내용을 한눈에 이해할 수 있도록 정리

[2] 주요 정보 정리
- 중요한 사실, 주장, 근거들을 구조적으로 정리

[3] 쟁점 분석
- 의견이 갈리는 부분이 있다면:
  - 찬성 입장
  - 반대 입장
  - 각각의 근거

[4] 결론
- 균형 잡힌 시각에서 최종 정리

사용자 질문:
{query}

자막 전체:
{transcript}
"""


def analyze(query: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    full_text = " ".join(c["text"] for c in chunks)[:12000]

    return {
        "final_analysis": _call_gemini(_PROMPT_TEMPLATE.format(query=query, transcript=full_text)),
        "steps": ["single_llm"],
        "ad_score": -1,
        "mode": "baseline",
    }
