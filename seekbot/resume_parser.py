import os

try:
    import docx
except Exception:
    docx = None

try:
    import pdfplumber
except Exception:
    pdfplumber = None


def extract_text_from_pdf(path: str) -> str:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is required to parse PDF resumes.")
    text: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text.append(page.extract_text() or "")
    return "\n".join(text)


def extract_text_from_docx(path: str) -> str:
    if docx is None:
        raise RuntimeError("python-docx is required to parse DOCX resumes.")
    document = docx.Document(path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_resume_text(path: str) -> str:
    absolute_path = os.path.abspath(path)
    if not os.path.exists(absolute_path):
        raise FileNotFoundError(absolute_path)
    lower = absolute_path.lower()
    if lower.endswith(".pdf"):
        return extract_text_from_pdf(absolute_path)
    if lower.endswith(".doc") or lower.endswith(".docx"):
        return extract_text_from_docx(absolute_path)
    with open(absolute_path, "r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()
