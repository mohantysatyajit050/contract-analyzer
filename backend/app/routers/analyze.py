from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..extract_text import extract_text
from ..graph import full_graph, new_session_id, revision_graph
from ..schemas import AnalyzeResponse, ReviewRequest, ReviewResponse
from ..store import get_session, save_session

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_contract(
    file: UploadFile = File(...),
    company_name: str = Form(default=""),
    user_question: str = Form(default=""),
):
    raw_bytes = await file.read()
    try:
        document_text = extract_text(file.filename, raw_bytes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}") from exc

    if not document_text.strip():
        raise HTTPException(status_code=400, detail="No text could be extracted from the file.")

    session_id = new_session_id()
    initial_state = {
        "session_id": session_id,
        "filename": file.filename,
        "document_text": document_text,
        "user_question": user_question,
        "company_name": company_name or None,
    }

    result = full_graph.invoke(initial_state)
    save_session(result)

    return AnalyzeResponse(
        session_id=session_id,
        filename=result["filename"],
        is_contract=result.get("is_contract", True),
        document_type_reason=result.get("document_type_reason"),
        company_context=result.get("company_context", {}),
        clauses=result.get("clauses", []),
        clause_analysis=result.get("clause_analysis", []),
        risk_summary=result.get("risk_summary", ""),
        review_status=result.get("review_status", "pending"),
    )


@router.post("/review", response_model=ReviewResponse)
async def submit_review(payload: ReviewRequest):
    try:
        state = get_session(payload.session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if payload.decision not in ("approve", "request_changes"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'request_changes'")

    if payload.decision == "approve":
        state["review_status"] = "approved"
        save_session(state)
        return ReviewResponse(
            session_id=state["session_id"],
            review_status="approved",
            clause_analysis=state.get("clause_analysis", []),
            risk_summary=state.get("risk_summary", ""),
        )

    # request_changes: re-run analysis + report with the reviewer's notes,
    # looping the document back through the Contract Analyzer node.
    state["review_notes"] = payload.notes
    updated = revision_graph.invoke(state)
    updated["review_status"] = "pending"
    save_session(updated)

    return ReviewResponse(
        session_id=updated["session_id"],
        review_status="changes_requested",
        clause_analysis=updated.get("clause_analysis", []),
        risk_summary=updated.get("risk_summary", ""),
    )