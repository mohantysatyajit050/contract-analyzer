from app.graph import (
    contract_analyzer_node,
    extract_clauses_node,
    generate_report_node,
)


def test_extract_clauses_splits_on_blank_lines():
    state = {"document_text": "Clause one text.\n\nClause two text.\n\nClause three text."}
    result = extract_clauses_node(state)
    assert len(result["clauses"]) == 3
    assert result["clauses"][0]["id"] == "clause_1"
    assert result["clauses"][0]["text"] == "Clause one text."


def test_extract_clauses_handles_empty_document():
    state = {"document_text": ""}
    result = extract_clauses_node(state)
    assert len(result["clauses"]) == 1


def test_contract_analyzer_flags_risky_language_without_llm(monkeypatch):
    # No GROQ_API_KEY configured -> falls back to the heuristic classifier.
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    state = {
        "clauses": [
            {"id": "clause_1", "text": "The Vendor may terminate this agreement at its sole discretion."},
            {"id": "clause_2", "text": "Either party may terminate with 30 days written notice."},
        ],
        "company_context": {},
    }
    result = contract_analyzer_node(state)
    analysis = {a["clause_id"]: a for a in result["clause_analysis"]}

    assert analysis["clause_1"]["classification"] == "risky"
    assert analysis["clause_1"]["risk_level"] == "high"
    assert analysis["clause_2"]["classification"] == "standard"


def test_generate_report_counts_risky_clauses():
    state = {
        "clause_analysis": [
            {"clause_id": "clause_1", "classification": "risky", "risk_level": "high",
             "rationale": "", "redline_suggestion": None},
            {"clause_id": "clause_2", "classification": "standard", "risk_level": "low",
             "rationale": "", "redline_suggestion": None},
        ],
        "company_context": {},
    }
    result = generate_report_node(state)
    assert "1 clause(s) flagged" in result["risk_summary"]
    assert result["review_status"] == "pending"


def test_document_type_guard_rejects_non_contract(monkeypatch):
    from app.config import get_settings
    from app.graph import verify_document_type_node

    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()

    result = verify_document_type_node({"document_text": "Just some random text, not a contract."})
    assert result["is_contract"] is True
    assert "no groq_api_key" in result["document_type_reason"].lower()

    get_settings.cache_clear()  # don't leak this override into other tests


def test_reject_document_node_produces_rejection_summary():
    from app.graph import reject_document_node

    state = {"document_type_reason": "This looks like a resume, not a contract."}
    result = reject_document_node(state)

    assert result["review_status"] == "rejected"
    assert result["clauses"] == []
    assert result["clause_analysis"] == []
    assert "does not appear to be a contract" in result["risk_summary"]