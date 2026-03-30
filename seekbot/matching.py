import re
from typing import Iterable

def _normalize_text(text: str) -> str:
    return (text or "").lower()


def extract_taxonomy_keywords(text: str, taxonomy: list[tuple[str, list[str]]]) -> list[str]:
    haystack = _normalize_text(text)
    found: list[str] = []
    for canonical, patterns in taxonomy:
        for pattern in patterns:
            if re.search(pattern, haystack):
                found.append(canonical)
                break
    return sorted(set(found))


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9.+#/:-]{1,}", _normalize_text(text))
        if len(token) > 2 and token not in {"with", "from", "that", "this", "have", "your"}
    }


def _fallback_keyword_overlap(resume_text: str, job_text: str) -> tuple[float, list[str], list[str]]:
    job_tokens = _tokenize(job_text)
    resume_tokens = _tokenize(resume_text)
    if not job_tokens:
        return 0.0, [], []
    matched = sorted(job_tokens & resume_tokens)
    missing = sorted(job_tokens - resume_tokens)[:25]
    return len(matched) / len(job_tokens), matched[:25], missing


def _score_overlap(job_keywords: Iterable[str], resume_keywords: Iterable[str]) -> tuple[float, list[str], list[str]]:
    job_set = set(job_keywords)
    resume_set = set(resume_keywords)
    if not job_set:
        return 0.0, [], []
    matched = sorted(job_set & resume_set)
    missing = sorted(job_set - resume_set)
    return len(matched) / len(job_set), matched, missing


def compute_compatibility(resume_text: str, job_text: str, config: dict, *, resume_keywords: list[str] | None = None) -> dict:
    taxonomy = list((config.get("matching", {}) or {}).get("taxonomy", []))
    resolved_resume_keywords = list(resume_keywords) if resume_keywords is not None else extract_taxonomy_keywords(resume_text, taxonomy)
    job_keywords = extract_taxonomy_keywords(job_text, taxonomy)

    if job_keywords:
        ratio, matched, missing = _score_overlap(job_keywords, resolved_resume_keywords)
    else:
        ratio, matched, missing = _fallback_keyword_overlap(resume_text, job_text)

    return {
        "score": round(ratio * 10, 1),
        "matched_keywords": matched,
        "missing_keywords": missing,
        "resume_keywords": resolved_resume_keywords,
        "job_keywords": job_keywords,
    }
