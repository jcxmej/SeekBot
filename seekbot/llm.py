import json
import logging
import re
import time

from seekbot.llm_providers import create_provider

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
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return None
    return None


def _clean_answer(text: str | None, max_chars: int | None = None) -> str:
    if not text:
        return ""
    data = _extract_json(text)
    if isinstance(data, dict):
        for key in ["answer", "response", "result"]:
            if key in data:
                text = str(data[key])
                break
    cleaned = text.strip()
    answer_match = re.search(r"(?:^|\b)(?:answer|response)\s*[:\-]\s*(.+)$", cleaned, flags=re.I | re.S)
    if answer_match:
        cleaned = answer_match.group(1).strip()
    cleaned = re.sub(r"^(answer|response)\s*[:\-]\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^here is (the )?(tailored )?cover letter\s*:\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^cover letter\s*:\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^.*?\bstandard answers?\b.*?(?:answer|response)\s*[:\-]\s*", "", cleaned, flags=re.I | re.S)
    cleaned = cleaned.strip().strip('"').strip("'")
    if "\n" in cleaned:
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        if lines:
            cleaned = lines[-1]
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if max_chars and len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip()
    return cleaned


def _extract_question_payload(text: str | None, options: list[str] | None, max_chars: int | None = None) -> dict:
    data = _extract_json(text)
    answer = ""
    confidence = 0.0
    reason = ""
    question_issue = ""
    if isinstance(data, dict):
        for key in ["answer", "response", "result"]:
            if key in data:
                answer = _clean_answer(str(data[key]), max_chars)
                break
        raw_confidence = data.get("confidence")
        try:
            confidence = float(raw_confidence)
        except Exception:
            confidence = 0.0
        if "reason" in data:
            reason = _clean_answer(str(data.get("reason", "")), 200)
        if "question_issue" in data:
            question_issue = _clean_answer(str(data.get("question_issue", "")), 200)
    if not answer:
        answer = _clean_answer(text, max_chars)
    if options:
        answer = _canonicalize_option_answer(answer, options)
    confidence = min(max(confidence, 0.0), 1.0)
    if answer and confidence == 0.0:
        confidence = 0.25
    return {"answer": answer, "confidence": confidence, "reason": reason, "question_issue": question_issue}


def _normalize_option_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())).strip()


def _canonicalize_option_answer(answer: str, options: list[str] | None) -> str:
    if not answer or not options:
        return answer
    option_map = {_normalize_option_text(option): option for option in options if option}
    parts = [part.strip() for part in answer.split(",") if part.strip()]
    if not parts:
        parts = [answer]
    resolved: list[str] = []
    for part in parts:
        normalized = _normalize_option_text(part)
        if normalized in option_map:
            resolved.append(option_map[normalized])
    if resolved:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in resolved:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return ", ".join(deduped)
    return answer


def _clean_cover_letter_text(text: str | None, signature_name: str) -> str:
    if not text:
        return ""
    cleaned = str(text).strip()
    cleaned = cleaned.strip('"').strip("'")
    cleaned = cleaned.replace("\r\n", "\n")
    cleaned = re.sub(r"^here is (the )?(tailored )?cover letter\s*:\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^cover letter\s*:\s*", "", cleaned, flags=re.I)
    if not cleaned:
        return ""
    cleaned = re.sub(r"^dear hiring manager\s*,?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"kind regards\s*,?\s*" + re.escape(signature_name) + r"\s*$", "", cleaned, flags=re.I)
    cleaned = cleaned.strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    if cleaned:
        body = cleaned
    else:
        body = ""
    return f"Dear Hiring Manager,\n\n{body}\n\nKind regards,\n{signature_name}".strip()


def _unknown(text: str) -> bool:
    return text.strip().lower() in {"", "n/a", "na", "unknown", "not applicable", "not sure", "unsure"}


def _generate(provider: str, llm_cfg: dict, prompt: str) -> str:
    return create_provider(provider).generate(prompt, llm_cfg)


def build_question_prompt(
    resume_text: str,
    job_text: str,
    question_text: str,
    config: dict,
    options: list[str] | None = None,
    qa_memory_table: str = "N/A",
) -> str:
    llm_cfg = config.get("llm", {})
    prompt_key = "option_question_prompt" if options else "question_prompt"
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


def parse_question_response(raw_text: str | None, options: list[str] | None, config: dict) -> dict:
    llm_cfg = config.get("llm", {})
    return _extract_question_payload(raw_text, options, llm_cfg.get("question_max_answer_chars", 400))


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
    )
    if not prompt:
        return None
    provider = llm_cfg.get("provider", "ollama").lower()
    started = time.time()
    if _LOGGER:
        _LOGGER.info(
            "LLM question request: provider=%s model=%s question=%s options=%d choices=%s",
            provider,
            llm_cfg.get("model", ""),
            (question_text or "")[:200],
            len(options or []),
            [str(item)[:80] for item in (options or [])[:8]],
        )
    for attempt in range(2):
        try:
            result = parse_question_response(_generate(provider, llm_cfg, prompt), options, config)
            answer = result.get("answer", "")
            confidence = float(result.get("confidence") or 0.0)
            question_issue = (result.get("question_issue") or "").strip()
            if _unknown(answer):
                return {"answer": "", "confidence": confidence, "reason": (result.get("reason") or "").strip(), "question_issue": question_issue}
            reason = (result.get("reason") or "").strip()
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
            return {"answer": answer, "confidence": confidence, "reason": reason, "question_issue": question_issue}
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
            answer = _clean_cover_letter_text(
                _generate(provider, llm_cfg, payload),
                signature_name,
            )
            max_chars = llm_cfg.get("cover_letter_max_chars", 900)
            if max_chars and len(answer) > max_chars:
                prefix = "Dear Hiring Manager,\n\n"
                suffix = f"\n\nKind regards,\n{signature_name}"
                body = answer.removeprefix(prefix)
                if body.endswith(suffix):
                    body = body[: -len(suffix)]
                available = max(0, max_chars - len(prefix) - len(suffix))
                body = body[:available].rstrip()
                answer = f"{prefix}{body}{suffix}"
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
            data = _extract_json(_generate(provider, llm_cfg, payload))
            if isinstance(data, dict):
                return {
                    "name": str(data.get("name", "") or "").strip(),
                    "email": str(data.get("email", "") or "").strip(),
                    "phone": str(data.get("phone", "") or "").strip(),
                }
            return None
        except Exception as exc:
            if attempt == 0:
                time.sleep(0.8)
                continue
            logging.warning("LLM contact call failed; falling back: %s", exc)
            if _LOGGER:
                _LOGGER.info("LLM contact failed: %s", exc)
            return None
    return None
