import io


def extract_text(filename: str, raw_bytes: bytes) -> str:
    lower = filename.lower()

    if lower.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw_bytes))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)

    if lower.endswith(".docx"):
        from docx import Document

        doc = Document(io.BytesIO(raw_bytes))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

    # Fall back to plain text
    return raw_bytes.decode("utf-8", errors="ignore")