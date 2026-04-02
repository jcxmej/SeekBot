import logging
import math
import re
from typing import Iterable

_EMBEDDING_MODELS: dict[str, object | None] = {}
_LOGGED_EMBEDDING_FAILURES: set[str] = set()


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


def _load_embedding_model(model_name: str):
    if model_name in _EMBEDDING_MODELS:
        model = _EMBEDDING_MODELS[model_name]
        if model is None:
            raise RuntimeError(f"Embedding model unavailable: {model_name}")
        return model
    from sentence_transformers import SentenceTransformer

    try:
        model = SentenceTransformer(model_name)
        _EMBEDDING_MODELS[model_name] = model
        return model
    except Exception:
        _EMBEDDING_MODELS[model_name] = None
        raise


def semantic_embedding(text: str, config: dict) -> tuple[float, ...]:
    matching_cfg = (config.get("matching", {}) or {})
    if not matching_cfg.get("semantic_enabled", True):
        return tuple()
    model_name = matching_cfg.get("embedding_model", "all-MiniLM-L6-v2")
    try:
        model = _load_embedding_model(model_name)
        vector = model.encode(text or "", normalize_embeddings=True, show_progress_bar=False)
        return tuple(float(item) for item in vector.tolist())
    except Exception as exc:
        if model_name not in _LOGGED_EMBEDDING_FAILURES:
            logging.warning("Semantic matching unavailable; falling back to lexical scoring: %s", exc)
            _LOGGED_EMBEDDING_FAILURES.add(model_name)
        return tuple()


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    a = list(left)
    b = list(right)
    if not a or not b or len(a) != len(b):
        return 0.0
    numerator = sum(x * y for x, y in zip(a, b))
    left_norm = math.sqrt(sum(x * x for x in a))
    right_norm = math.sqrt(sum(y * y for y in b))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _normalize_semantic_ratio(raw_cosine: float, config: dict) -> float:
    matching_cfg = (config.get("matching", {}) or {})
    floor = float(matching_cfg.get("semantic_floor_cosine", 0.15))
    ceiling = float(matching_cfg.get("semantic_full_cosine", 0.55))
    if ceiling <= floor:
        return _clamp(raw_cosine)
    return _clamp((raw_cosine - floor) / (ceiling - floor))


def compute_compatibility(
    resume_text: str,
    job_text: str,
    config: dict,
    *,
    resume_keywords: list[str] | None = None,
    resume_embedding: tuple[float, ...] | None = None,
    job_keywords: list[str] | None = None,
    job_embedding: tuple[float, ...] | None = None,
) -> dict:
    matching_cfg = (config.get("matching", {}) or {})
    taxonomy = list(matching_cfg.get("taxonomy", []))

    resolved_resume_keywords = list(resume_keywords) if resume_keywords is not None else extract_taxonomy_keywords(resume_text, taxonomy)
    resolved_job_keywords = list(job_keywords) if job_keywords is not None else extract_taxonomy_keywords(job_text, taxonomy)

    if resolved_job_keywords:
        keyword_ratio, matched, missing = _score_overlap(resolved_job_keywords, resolved_resume_keywords)
    else:
        keyword_ratio, matched, missing = _fallback_keyword_overlap(resume_text, job_text)

    raw_semantic_cosine = 0.0
    semantic_ratio = 0.0
    resolved_job_embedding = tuple(job_embedding or ()) or semantic_embedding(job_text, config)
    resolved_resume_embedding = tuple(resume_embedding or ()) or semantic_embedding(resume_text, config)
    if resolved_job_embedding and resolved_resume_embedding:
        raw_semantic_cosine = max(0.0, cosine_similarity(resolved_resume_embedding, resolved_job_embedding))
        semantic_ratio = _normalize_semantic_ratio(raw_semantic_cosine, config)

    semantic_weight = float(matching_cfg.get("semantic_weight", 0.7))
    keyword_weight = float(matching_cfg.get("keyword_weight", 0.3))
    if semantic_ratio > 0.0 and keyword_ratio > 0.0:
        ratio = (semantic_ratio * semantic_weight) + (keyword_ratio * keyword_weight)
    elif semantic_ratio > 0.0:
        ratio = semantic_ratio
    else:
        ratio = keyword_ratio

    return {
        "score": round(ratio * 10, 1),
        "semantic_score": round(semantic_ratio * 10, 1),
        "semantic_cosine": round(raw_semantic_cosine, 3),
        "keyword_score": round(keyword_ratio * 10, 1),
        "matched_keywords": matched,
        "missing_keywords": missing,
        "resume_keywords": resolved_resume_keywords,
        "job_keywords": resolved_job_keywords,
    }
