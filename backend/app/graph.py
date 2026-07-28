"""
LangGraph pipeline for the contract clause analyzer.

Pipeline: extract_clauses_node -> researcher_node -> contract_analyzer_node -> generate_report_node

The Researcher agent gathers PUBLIC CONTEXT ONLY about the counterparty
company. It never asserts a verdict about trustworthiness or legality --
that judgment call is left to the human reviewer.
"""

import re
import uuid
from typing import List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from .config import get_settings

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

try:
    from groq import Groq
except ImportError:
    Groq = None


class ClauseAnalysisDict(TypedDict):
    clause_id: str
    classification: str
    risk_level: str
    rationale: str
    redline_suggestion: Optional[str]


class ContractState(TypedDict, total=False):
    session_id: str
    filename: str
    document_text: str
    user_question: str
    company_name: Optional[str]
    company_context: dict
    clauses: List[dict]
    clause_analysis: List[ClauseAnalysisDict]
    risk_summary: str
    review_status: str
    review_notes: Optional[str]




# ---------------------------------------------------------------------------
# Node 1: extract_clauses_node
# ---------------------------------------------------------------------------
def extract_clauses_node(state: ContractState) -> ContractState:
    """Split the raw contract text into individually addressable clauses.

    Stub strategy: split on blank-line-separated paragraphs. Replace with a
    proper legal-document segmenter (or an LLM-based splitter) once real
    contracts are tested -- numbered clauses, sub-clauses, and multi-column
    layouts will break this naive approach.
    """
    text = state.get("document_text", "")
    raw_chunks = re.split(r"\n\s*\n", text.strip()) if text else []

    clauses = []
    for i, chunk in enumerate(raw_chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        clauses.append({"id": f"clause_{i + 1}", "text": chunk})

    if not clauses:
        clauses = [{"id": "clause_1", "text": text}]

    return {**state, "clauses": clauses}



def _get_tavily_client() -> Optional["TavilyClient"]: # type: ignore
    settings = get_settings()
    if not TavilyClient or not settings.tavily_api_key:
        return None
    return TavilyClient(api_key=settings.tavily_api_key)


# ---------------------------------------------------------------------------
# Node 2: researcher_node
# ---------------------------------------------------------------------------
def researcher_node(state: ContractState) -> ContractState:
    """Gather PUBLIC CONTEXT about the counterparty company via web search.

    Important: this node reports what it finds. It does not decide whether
    the company is "trustworthy" or "legal" -- that inference is unreliable
    from search results alone and is left to the human reviewer.
    """
    company_name = state.get("company_name")
    client = _get_tavily_client()

    if not company_name:
        return {
            **state,
            "company_context": {
                "company_name": None,
                "summary": "No company name was provided; skipping research step.",
                "sources": [],
            },
        }

    if client is None:
        # No TAVILY_API_KEY configured -- return a placeholder so the rest
        # of the pipeline can still be exercised end-to-end.
        return {
            **state,
            "company_context": {
                "company_name": company_name,
                "summary": (
                    f"[stub] Set TAVILY_API_KEY to enable live research on "
                    f"'{company_name}'. No search performed."
                ),
                "sources": [],
            },
        }

    query = f"{company_name} company official policies public information"
    results = client.search(query=query, max_results=5)
    sources = [r.get("url", "") for r in results.get("results", [])]
    snippets = " ".join(r.get("content", "") for r in results.get("results", []))

    return {
        **state,
        "company_context": {
            "company_name": company_name,
            "summary": snippets[:1500],
            "sources": sources,
        },
    }



CLAUSE_ANALYSIS_SYSTEM_PROMPT = """You are a contract review assistant.
For the given clause, classify it as one of: standard, risky, missing, non_standard.
Assign a risk_level of low, medium, or high.
Give a one-sentence rationale.
If risky or non_standard, suggest a redline (a rewritten version of the clause).
Respond ONLY as JSON with keys: classification, risk_level, rationale, redline_suggestion.
"""


def _get_groq_client() -> Optional["Groq"]:
    settings = get_settings()
    if not Groq or not settings.groq_api_key:
        return None
    return Groq(api_key=settings.groq_api_key)


def _classify_clause_stub(clause_text: str) -> ClauseAnalysisDict:
    """Fallback classifier used when no GROQ_API_KEY is configured."""
    lower = clause_text.lower()
    risky_markers = ["sole discretion", "waive", "indemnif", "perpetual", "non-refundable"]
    if any(marker in lower for marker in risky_markers):
        return {
            "clause_id": "",
            "classification": "risky",
            "risk_level": "high",
            "rationale": "Contains language commonly associated with one-sided terms.",
            "redline_suggestion": "Consider adding mutual/reasonable qualifiers to this clause.",
        }
    return {
        "clause_id": "",
        "classification": "standard",
        "risk_level": "low",
        "rationale": "No unusual or one-sided language detected.",
        "redline_suggestion": None,
    }


def _classify_clause_llm(
    client: "Groq", clause_text: str, company_context: dict, review_notes: Optional[str]
) -> ClauseAnalysisDict:
    import json

    user_prompt = f"Clause:\n{clause_text}\n\nCompany context:\n{company_context.get('summary', '')}"
    if review_notes:
        user_prompt += f"\n\nHuman reviewer notes to address in this pass:\n{review_notes}"

    completion = client.chat.completions.create(
        model=get_settings().llm_model,
        messages=[
            {"role": "system", "content": CLAUSE_ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    raw = completion.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {
            "classification": "non_standard",
            "risk_level": "medium",
            "rationale": "Model response could not be parsed; flagged for manual review.",
            "redline_suggestion": None,
        }
    parsed["clause_id"] = ""
    return parsed


# ---------------------------------------------------------------------------
# Node 3: contract_analyzer_node
# ---------------------------------------------------------------------------
def contract_analyzer_node(state: ContractState) -> ContractState:
    """Classify each clause and draft redlines for risky ones."""
    client = _get_groq_client()
    company_context = state.get("company_context", {})
    review_notes = state.get("review_notes")

    analysis: List[ClauseAnalysisDict] = []
    for clause in state.get("clauses", []):
        if client is not None:
            result = _classify_clause_llm(client, clause["text"], company_context, review_notes)
        else:
            result = _classify_clause_stub(clause["text"])
        result["clause_id"] = clause["id"]
        analysis.append(result)

    return {**state, "clause_analysis": analysis}




# ---------------------------------------------------------------------------
# Node 4: generate_report_node
# ---------------------------------------------------------------------------
def generate_report_node(state: ContractState) -> ContractState:
    analysis = state.get("clause_analysis", [])
    total = len(analysis)
    risky = [a for a in analysis if a["classification"] in ("risky", "non_standard")]
    high_risk = [a for a in analysis if a["risk_level"] == "high"]

    summary_lines = [
        f"Reviewed {total} clause(s).",
        f"{len(risky)} clause(s) flagged as risky or non-standard.",
        f"{len(high_risk)} clause(s) marked high risk.",
    ]
    company_context = state.get("company_context", {})
    if company_context.get("company_name"):
        summary_lines.append(
            f"Counterparty: {company_context['company_name']} "
            f"({len(company_context.get('sources', []))} public source(s) reviewed)."
        )

    return {
        **state,
        "risk_summary": " ".join(summary_lines),
        "review_status": "pending",
    }



# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
def build_full_graph():
    """Upload -> extract clauses -> research company -> analyze -> report."""
    graph = StateGraph(ContractState)
    graph.add_node("extract_clauses", extract_clauses_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("contract_analyzer", contract_analyzer_node)
    graph.add_node("generate_report", generate_report_node)

    graph.set_entry_point("extract_clauses")
    graph.add_edge("extract_clauses", "researcher")
    graph.add_edge("researcher", "contract_analyzer")
    graph.add_edge("contract_analyzer", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


def build_revision_graph():
    """Re-run just analysis + report after a human requests changes.

    Skips re-uploading and re-researching the company -- only the clause
    analysis is redone, informed by review_notes.
    """
    graph = StateGraph(ContractState)
    graph.add_node("contract_analyzer", contract_analyzer_node)
    graph.add_node("generate_report", generate_report_node)

    graph.set_entry_point("contract_analyzer")
    graph.add_edge("contract_analyzer", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


full_graph = build_full_graph()
revision_graph = build_revision_graph()


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]