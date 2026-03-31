import json
import logging
import re
import time

from pydantic import ValidationError

from seekbot.llm.providers import create_provider
from seekbot.llm.schemas import ContactExtraction, CoverLetter, QuestionAnswer

_LOGGER = None


def set_logger(logger) -> None:
    global _LOGGER
    _LOGGER = logger


def _truncate(text: str | None, limit: int | None) -> str:
    if not text:
        return ""
    if limit and len(text) > limit:
        return text[:limit]
    return text


def _extract_json(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _unknown(text: str) -> bool:
    return text.strip().lower() in {"", "n/a", "na", "unknown", "not applicable", "not sure", "unsure"}


def _normalize_option_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())).strip()


def _canonicalize_option_answer(answer: str, options: list[str] | None, allow_multiple: bool = False) -> str:
    if not answer or not options:
        return answer
    option_map = {_normalize_option_text(option): option for option in options if option}
    direct = option_map.get(_normalize_option_text(answer))
    if direct:
        return direct
    parts = [answer]
    if allow_multiple:
        split_parts = [part.strip() for part in re.split(r"\s*\|\|\s*|\s*,\s*", answer) if part.strip()]
        if split_parts:
            parts = split_parts
    resolved: list[str] = []
    for part in parts:
        normalized = _normalize_option_text(part)
        if normalized in option_map:
            resolved.append(option_map[normalized])
    if not resolved:
        return answer
    deduped: list[str] = []
    seen: set[str] = set()
    for item in resolved:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return ", ".join(deduped)


def _render_cover_letter(letter: CoverLetter, signature_name: str) -> str:
    paragraphs = [part.strip() for part in [letter.paragraph_one, letter.paragraph_two] if part and part.strip()]
    body = "\n\n".join(paragraphs).strip()
    if not body:
        return ""
    return f"Dear Hiring Manager,\n\n{body}\n\nKind regards,\n{signature_name}".strip()


def _generate(provider: str, llm_cfg: dict, prompt: str) -> str:
    return create_provider(provider).generate(prompt, llm_cfg)


def _generate_structured(provider: str, llm_cfg: dict, prompt: str, response_model: type):
    return create_provider(provider).generate_structured(prompt, llm_cfg, response_model)


def build_question_prompt(
    resume_text: str,
    job_text: str,
    question_text: str,
    config: dict,
    options: list[str] | None = None,
    qa_memory_table: str = "N/A",
    allow_multiple: bool = False,
) -> str:
    llm_cfg = config.get("llm", {})
    if options and allow_multiple:
        prompt_key = "multi_option_question_prompt"
    elif options:
        prompt_key = "option_question_prompt"
    else:
        prompt_key = "question_prompt"
    prompt = llm_cfg.get(prompt_key, "") or llm_cfg.get("question_prompt", "")
    if not prompt:
        return ""
    return prompt.format(
        resume=resume_text or "",
        job=_truncate(job_text, llm_cfg.get("max_job_chars", 4000)),
        question=question_text,
        options="\n".join(f"- {item}" for item in (options or [])) or "N/A",
        qa_memory_table=qa_memory_table or "N/A",
    )


def _question_answer_to_dict(result: QuestionAnswer, options: list[str] | None = None, allow_multiple: bool = False) -> dict:
    answer = _canonicalize_option_answer(result.answer or "", options, allow_multiple=allow_multiple)
    confidence = min(max(float(result.confidence or 0.0), 0.0), 1.0)
    return {
        "answer": answer,
        "confidence": confidence,
        "reason": (result.reason or "").strip(),
        "question_issue": (result.question_issue or "").strip(),
    }


def parse_question_response(raw_text: str | None, options: list[str] | None, allow_multiple: bool = False) -> dict:
    data = _extract_json(raw_text)
    if isinstance(data, dict):
        try:
            return _question_answer_to_dict(QuestionAnswer.model_validate(data), options, allow_multiple=allow_multiple)
        except ValidationError:
            pass
    fallback = QuestionAnswer(answer=(raw_text or "").strip(), confidence=0.0, reason="", question_issue="")
    return _question_answer_to_dict(fallback, options, allow_multiple=allow_multiple)


def generate_with_current_provider(prompt: str, config: dict) -> str:
    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "ollama").lower()
    return _generate(provider, llm_cfg, prompt)


def answer_question(
    resume_text: str,
    job_text: str,
    question_text: str,
    config: dict,
    options: list[str] | None = None,
    qa_memory_table: str = "N/A",
    allow_multiple: bool = False,
) -> dict | None:
    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("enabled"):
        return None
    prompt = build_question_prompt(
        resume_text,
        job_text,
        question_text,
        config,
        options,
        qa_memory_table=qa_memory_table,
        allow_multiple=allow_multiple,
    )
    if not prompt:
        return None
    provider = llm_cfg.get("provider", "ollama").lower()
    started = time.time()
    if _LOGGER:
        _LOGGER.info(
            "LLM question request: provider=%s model=%s multi=%s question=%s options=%d choices=%s",
            provider,
            llm_cfg.get("model", ""),
            allow_multiple,
            (question_text or "")[:200],
            len(options or []),
            [str(item)[:80] for item in (options or [])[:8]],
        )
    for attempt in range(2):
        try:
            structured = _generate_structured(provider, llm_cfg, prompt, QuestionAnswer)
            result = _question_answer_to_dict(structured, options, allow_multiple=allow_multiple)
            answer = result.get("answer", "")
            confidence = float(result.get("confidence") or 0.0)
            question_issue = (result.get("question_issue") or "").strip()
            reason = (result.get("reason") or "").strip()
            if _unknown(answer):
                return {"answer": "", "confidence": confidence, "reason": reason, "question_issue": question_issue}
            if _LOGGER:
                _LOGGER.info(
                    "LLM question ok: duration_ms=%d question=%s answer=%s confidence=%.2f reason=%s question_issue=%s",
                    int((time.time() - started) * 1000),
                    (question_text or "")[:200],
                    answer[:200],
                    confidence,
                    reason[:200],
                    question_issue[:200],
                )
            return result
        except Exception as exc:
            if attempt == 0:
                time.sleep(0.8)
                continue
            logging.warning("LLM question call failed; falling back: %s", exc)
            if _LOGGER:
                _LOGGER.info("LLM question failed: %s", exc)
            return None
    return None


def generate_cover_letter(resume_text: str, job_text: str, config: dict) -> str | None:
    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("enabled"):
        return None
    prompt = llm_cfg.get("cover_letter_prompt", "")
    if not prompt:
        return None
    payload = prompt.format(
        resume=resume_text or "",
        job=_truncate(job_text, llm_cfg.get("max_job_chars", 4000)),
        signature_name=llm_cfg.get("cover_letter_signature_name", "Candidate"),
    )
    provider = llm_cfg.get("provider", "ollama").lower()
    started = time.time()
    if _LOGGER:
        _LOGGER.info("LLM cover letter request: provider=%s model=%s", provider, llm_cfg.get("model", ""))
    for attempt in range(2):
        try:
            signature_name = llm_cfg.get("cover_letter_signature_name", "Candidate")
            structured = _generate_structured(provider, llm_cfg, payload, CoverLetter)
            answer = _render_cover_letter(structured, signature_name)
            max_chars = llm_cfg.get("cover_letter_max_chars", 900)
            if max_chars and len(answer) > max_chars:
                prefix = "Dear Hiring Manager,\n\n"
                suffix = f"\n\nKind regards,\n{signature_name}"
                body = "\n\n".join(part.strip() for part in [structured.paragraph_one, structured.paragraph_two] if part and part.strip())
                available = max(0, max_chars - len(prefix) - len(suffix))
                answer = f"{prefix}{body[:available].rstrip()}{suffix}".strip()
            if _unknown(answer):
                if _LOGGER:
                    _LOGGER.info("LLM cover letter unusable response")
                return None
            if _LOGGER:
                _LOGGER.info(
                    "LLM cover letter ok: duration_ms=%d chars=%d preview=%s",
                    int((time.time() - started) * 1000),
                    len(answer),
                    answer[:250],
                )
            return answer
        except Exception as exc:
            if attempt == 0:
                time.sleep(0.8)
                continue
            logging.warning("LLM cover letter call failed; falling back: %s", exc)
            if _LOGGER:
                _LOGGER.info("LLM cover letter failed: %s", exc)
            return None
    return None


def extract_contact(job_text: str, config: dict) -> dict | None:
    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("enabled"):
        return None
    prompt = llm_cfg.get("contact_prompt", "")
    if not prompt:
        return None
    payload = prompt.format(job=_truncate(job_text, llm_cfg.get("max_job_chars", 4000)))
    provider = llm_cfg.get("provider", "ollama").lower()
    if _LOGGER:
        _LOGGER.info("LLM contact request: provider=%s model=%s", provider, llm_cfg.get("model", ""))
    for attempt in range(2):
        try:
            structured = _generate_structured(provider, llm_cfg, payload, ContactExtraction)
            return structured.model_dump()
        except Exception as exc:
            if attempt == 0:
                time.sleep(0.8)
                continue
            logging.warning("LLM contact call failed; falling back: %s", exc)
            if _LOGGER:
                _LOGGER.info("LLM contact failed: %s", exc)
            return None
    return None
