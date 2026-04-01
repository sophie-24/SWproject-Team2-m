from typing import TypedDict, List, Annotated, Dict, Any
import operator
import os
import re
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

# 환경변수 로드
load_dotenv()

gemini_key = os.getenv("GEMINI_API_KEY")
if not gemini_key:
    raise ValueError("GEMINI_API_KEY가 .env에 설정되지 않았습니다.")

genai.configure(api_key=gemini_key)
model = genai.GenerativeModel("gemini-2.5-flash-lite")

MAX_STEPS = 10


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception(lambda e: "429" in str(e)),
)
def _call_gemini(prompt: str, temperature: float = 0.3) -> str:
    response = model.generate_content(
        prompt,
        generation_config={"temperature": temperature},
    )
    if response.text is None:
        finish = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        raise ValueError(f"Gemini 응답 없음 (finish_reason: {finish})")
    return response.text

RAG_K = 5
RAG_K_REANALYZE = 3
RAG_DISTANCE_THRESHOLD = 1.5

# ──────────────────────────────────────────────
# 1. 상태 정의
# ──────────────────────────────────────────────
class AgentState(TypedDict):
    query: str
    video_id: str
    chunks: List[Dict[str, Any]]
    ad_score: int
    final_analysis: str
    steps: Annotated[List[str], operator.add]
    step_count: int
    user_context: Dict[str, Any]

# ──────────────────────────────────────────────
# 2. ChromaDB / RAG 설정
# ──────────────────────────────────────────────
chroma_client = chromadb.PersistentClient(path="./chroma_db")

local_ef = SentenceTransformerEmbeddingFunction(
    model_name="paraphrase-multilingual-MiniLM-L12-v2"
)

collection = chroma_client.get_or_create_collection(
    name="youtube_transcript",
    embedding_function=local_ef
)

def add_chunks_to_vectorstore(video_id: str, chunks: list):
    """[RAG 1단계] 전처리된 청크들을 벡터 DB에 저장합니다."""
    ids, documents, metadatas = [], [], []

    for i, chunk in enumerate(chunks):
        ids.append(f"{video_id}_{i}")
        documents.append(chunk["text"])
        metadatas.append({
            "video_id": video_id,
            "timestamp": chunk["metadata"]["timestamp"],
            "quality_score": chunk["metadata"]["quality_score"]
        })

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    print(f"--- [RAG] {video_id} 관련 {len(documents)}개 청크 적재 완료 ---")

def query_vectorstore(query: str, k: int = RAG_K) -> List[str]:
    results = collection.query(
        query_texts=[query],
        n_results=k,
        include=["documents", "distances"],
    )
    docs = results["documents"][0]
    distances = results["distances"][0]
    filtered = [doc for doc, dist in zip(docs, distances) if dist <= RAG_DISTANCE_THRESHOLD]
    return filtered if filtered else docs[:1]

# ──────────────────────────────────────────────
# 3. 프롬프트 헬퍼
# ──────────────────────────────────────────────
def build_analysis_prompt(query: str, context: str) -> str:
    return f"""
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

참고 자막:
{context}
"""

# ──────────────────────────────────────────────
# 4. 노드 함수 정의
# ──────────────────────────────────────────────
def detect_ads_node(state: AgentState) -> Dict[str, Any]:
    print(f"--- [Step 1] {state['video_id']} 영상 광고 점수 산출 중 (Gemini) ---")

    full_text = " ".join([chunk["text"] for chunk in state["chunks"]])
    prompt = f"""
다음 영상이 광고/홍보성 콘텐츠인지 판단하세요.
숫자만 답하세요 (다른 텍스트 없이 0~100 사이 정수만):
- 0: 광고 아님
- 100: 명백한 광고

분석할 자막 내용:
{full_text[:8000]}
"""

    try:
        text = _call_gemini(prompt, temperature=0)
        match = re.search(r'\d+', text.strip())
        score = int(match.group()) if match else 0
        score = max(0, min(100, score))
    except Exception as e:
        import traceback
        traceback.print_exc()
        # cause = getattr(e, "__cause__", e)
        # print(f"  [광고 감지 오류] {cause} → 기본값 0 사용")
        score = 0

    return {"ad_score": score, "steps": ["detect_ads"], "step_count": state["step_count"] + 1}


def analyze_content_node(state: AgentState) -> Dict[str, Any]:
    print(f"--- [Step 2] RAG 기반 핵심 쟁점 분석 중 (Gemini) ---")

    relevant_chunks = query_vectorstore(state["query"], k=RAG_K)
    context_text = "\n".join(relevant_chunks)
    prompt = build_analysis_prompt(state["query"], context_text)

    try:
        text = _call_gemini(prompt, temperature=0.3)
    except Exception as e:
        cause = getattr(e, "__cause__", e)
        print(f"  [분석 오류] {cause}")
        text = "분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

    return {"final_analysis": text, "steps": ["analyze_content"], "step_count": state["step_count"] + 1}


def reanalyze_node(state: AgentState) -> Dict[str, Any]:
    print("--- [Step 2-Refine] 광고 제거 분석 ---")

    relevant_chunks = query_vectorstore(state["query"], k=RAG_K_REANALYZE)
    context_text = "\n".join(relevant_chunks)
    prompt = f"""
다음 자막은 광고가 포함되어 있을 수 있습니다.
홍보성 문장을 완전히 제외하고 분석하세요.

{build_analysis_prompt(state["query"], context_text)}
"""

    try:
        text = _call_gemini(prompt, temperature=0)
    except Exception as e:
        cause = getattr(e, "__cause__", e)
        print(f"  [재분석 오류] {cause}")
        text = "재분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

    return {
        "final_analysis": "[광고 제거 분석]\n" + text,
        "steps": ["reanalyze"],
        "step_count": state["step_count"] + 1,
    }


def personalize_node(state: AgentState) -> Dict[str, Any]:
    print("--- [Step 3] 사용자 맞춤 재정렬 중 (Gemini) ---")

    ctx = state["user_context"]
    subscriptions = ctx.get("subscribed_channels", [])
    searches = ctx.get("recent_searches", [])

    if not subscriptions and not searches:
        return {"steps": ["personalize"], "step_count": state["step_count"] + 1}

    prompt = f"""
아래는 유튜브 영상에 대한 분석 결과입니다.
사용자의 관심사를 참고하여 가장 관련 있는 내용을 앞에 배치하고, 관련도가 낮은 내용은 간략히 정리하세요.
분석 결과의 사실은 바꾸지 말고, 순서와 강조점만 조정하세요.

구독 채널: {', '.join(subscriptions) if subscriptions else '정보 없음'}
최근 검색어: {', '.join(searches) if searches else '정보 없음'}

원본 분석:
{state['final_analysis']}
"""

    try:
        text = _call_gemini(prompt, temperature=0.2)
    except Exception as e:
        print(f"  [개인화 오류] {e}")
        text = state["final_analysis"]

    return {
        "final_analysis": text,
        "steps": ["personalize"],
        "step_count": state["step_count"] + 1,
    }

# ──────────────────────────────────────────────
# 5. 라우팅 함수
# ──────────────────────────────────────────────
def decide_next_step(state: AgentState) -> str:
    if state["step_count"] >= MAX_STEPS:
        return END
    if state["ad_score"] >= 70:
        return "reanalyze"
    return "analyze_content"

# ──────────────────────────────────────────────
# 6. 그래프 구성
# ──────────────────────────────────────────────
workflow = StateGraph(AgentState)
workflow.add_node("detect_ads", detect_ads_node)
workflow.add_node("analyze_content", analyze_content_node)
workflow.add_node("reanalyze", reanalyze_node)
workflow.add_node("personalize", personalize_node)
workflow.set_entry_point("detect_ads")

workflow.add_conditional_edges(
    "detect_ads",
    decide_next_step,
    {"reanalyze": "reanalyze", "analyze_content": "analyze_content", END: END}
)

workflow.add_edge("analyze_content", "personalize")
workflow.add_edge("reanalyze", "personalize")
workflow.add_edge("personalize", END)

orchestrator_app = workflow.compile()
