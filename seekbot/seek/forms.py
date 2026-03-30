import re
import sys

from playwright.sync_api import Page

from seekbot.llm import answer_question


def is_placeholder_answer(answer) -> bool:
    if answer is None:
        return True
    text = str(answer).strip()
    if not text:
        return True
    upper = text.upper()
    return upper.startswith("REPLACE_") or upper in {"TODO", "TBD", "UNKNOWN"}


def normalize_choice(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def exact_option_match(options: list[str] | None, answer: str | None) -> str | None:
    if not options or not answer:
        return None
    normalized_answer = normalize_choice(answer)
    for option in options:
        if normalize_choice(option) == normalized_answer:
            return option
    return None


def _get_question_text(field) -> str:
    script = """
    el => {
      const direct = (el.labels && el.labels.length ? el.labels[0].innerText : '') || '';
      if (direct.trim()) return direct.trim();
      const labelledBy = (el.getAttribute('aria-labelledby') || '').trim();
      if (labelledBy) {
        const parts = labelledBy.split(/\\s+/).map(id => document.getElementById(id)).filter(Boolean).map(node => (node.innerText || '').trim()).filter(Boolean);
        if (parts.length) return parts.join(' ');
      }
      const placeholder = (el.getAttribute('placeholder') || '').trim();
      if (placeholder) return placeholder;
      const fieldset = el.closest('fieldset');
      if (fieldset) {
        const legend = fieldset.querySelector('legend');
        if (legend && (legend.innerText || '').trim()) return legend.innerText.trim();
      }
      let cur = el;
      for (let i = 0; i < 4 && cur; i++) {
        cur = cur.parentElement;
        if (!cur) break;
        const txt = (cur.innerText || '').trim();
        if (txt && txt.length <= 200 && txt.includes('?')) return txt;
      }
      return '';
    }
    """
    try:
        return field.evaluate(script) or ""
    except Exception:
        return ""


def _descriptor_text(field, question_text: str = "") -> str:
    attrs = [question_text]
    for attr in ["id", "name", "data-testid", "aria-label", "placeholder"]:
        try:
            attrs.append(field.get_attribute(attr) or "")
        except Exception:
            continue
    try:
        ancestor_text = field.evaluate(
            """
            el => {
              let cur = el;
              for (let i = 0; i < 4 && cur; i++) {
                cur = cur.parentElement;
                if (!cur) break;
                const txt = (cur.innerText || '').trim();
                if (txt) return txt.slice(0, 400);
              }
              return '';
            }
            """
        ) or ""
        attrs.append(ancestor_text)
    except Exception:
        pass
    return " ".join(attrs).lower()


def _get_radio_group_question(field) -> str:
    script = """
    el => {
      const fieldset = el.closest('fieldset');
      if (fieldset) {
        const legend = fieldset.querySelector('legend');
        if (legend && (legend.innerText || '').trim()) return legend.innerText.trim();
      }
      let cur = el;
      for (let i = 0; i < 5 && cur; i++) {
        cur = cur.parentElement;
        if (!cur) break;
        const txt = (cur.innerText || '').trim();
        if (!txt) continue;
        const lines = txt.split('\\n').map(line => line.trim()).filter(Boolean);
        for (const line of lines) {
          const lower = line.toLowerCase();
          if (['yes', 'no', 'upload a resumé', 'select a resumé', \"don't include a resumé\", 'upload a cover letter', 'write a cover letter', \"don't include a cover letter\"].includes(lower)) continue;
          if (line.length > 8) return line;
        }
      }
      return '';
    }
    """
    try:
        return field.evaluate(script) or ""
    except Exception:
        return _get_question_text(field)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _looks_like_choice_label(question_text: str, options: list[str] | None = None) -> bool:
    normalized = normalize_choice(question_text)
    if not normalized:
        return True
    if normalized in {
        "yes",
        "no",
        "upload a resume",
        "select a resume",
        "dont include a resume",
        "upload a cover letter",
        "write a cover letter",
        "dont include a cover letter",
        "show strong interest",
    }:
        return True
    return any(normalized == normalize_choice(option) for option in (options or []) if option)


def _find_better_group_question(field, options: list[str]) -> str:
    fallback = _get_question_text(field)
    if fallback and not _looks_like_choice_label(fallback, options):
        return fallback
    descriptor = _descriptor_text(field, "")
    option_set = {normalize_choice(option) for option in options if option}
    for raw_line in descriptor.splitlines():
        line = _normalize_text(raw_line)
        if not line:
            continue
        lower = normalize_choice(line)
        if lower in option_set:
            continue
        if any(token in lower for token in ["resum", "cover letter", "strong interest", "make a strong impression"]):
            continue
        if "?" in line or len(line) > 20:
            return line
    return fallback


def _is_resume_field(field, question_text: str) -> bool:
    descriptor = _descriptor_text(field, question_text)
    return "resum" in descriptor


def _is_cover_letter_field(field, question_text: str) -> bool:
    descriptor = _descriptor_text(field, question_text)
    return "coverletter" in descriptor or "cover letter" in descriptor or "covering letter" in descriptor


def _is_non_question_control(question_text: str, options: list[str] | None = None) -> bool:
    lowered = (question_text or "").lower()
    if "show strong interest" in lowered or "make a strong impression" in lowered:
        return True
    if "resum" in lowered or "cover letter" in lowered or "coverletter" in lowered or "covering letter" in lowered:
        return True
    return _looks_like_choice_label(question_text, options)


def _is_visible_enabled(field) -> bool:
    try:
        return field.is_visible() and field.is_enabled()
    except Exception:
        return False


def _current_value(field) -> str:
    try:
        return field.evaluate(
            """
            el => {
              if (el.type === 'checkbox' || el.type === 'radio') return el.checked ? 'checked' : '';
              return (el.value || '').trim();
            }
            """
        ) or ""
    except Exception:
        return ""


def _selected_option_value(field) -> str:
    try:
        return field.evaluate(
            """
            el => {
              if (el.tagName.toLowerCase() !== 'select') return '';
              const selected = el.selectedOptions && el.selectedOptions.length ? el.selectedOptions[0] : null;
              return selected ? (selected.textContent || '').trim() : '';
            }
            """
        ) or ""
    except Exception:
        return ""


def build_qa_memory_table(config: dict, question_store, question_text: str, options: list[str] | None) -> str:
    lines = ["STANDARD_QA_TABLE", "question_key | answer"]
    for key, value in (config.get("question_answers", {}) or {}).items():
        if is_placeholder_answer(value):
            continue
        lines.append(f"{key} | {str(value).strip()}")
    prior = question_store.format_prompt_context(question_text, options) if question_store else "N/A"
    if prior != "N/A":
        lines.append("")
        lines.append("PRIOR_QUESTIONNAIRE_QA")
        lines.append(prior)
    return "\n".join(lines)


def _prompt_user_for_answer(
    question_text: str,
    options: list[str] | None,
    suggested_answer: str | None,
    confidence: float | None,
    reason: str | None,
    config: dict,
    run_logger=None,
) -> tuple[str | None, str | None, float | None]:
    if not sys.stdin.isatty():
        if run_logger:
            run_logger.info(
                "Employer question user prompt unavailable: question=%r suggested_answer=%r confidence=%.2f",
                question_text[:250],
                (suggested_answer or "")[:200],
                float(confidence or 0.0),
            )
        return None, None, None

    if run_logger:
        run_logger.info(
            "Employer question awaiting user input: question=%r options=%s suggested_answer=%r confidence=%.2f reason=%r",
            question_text[:250],
            (options or [])[:8],
            (suggested_answer or "")[:200],
            float(confidence or 0.0),
            (reason or "")[:200],
        )
    print("\n[SeekBot] Low-confidence questionnaire answer")
    print(f"Question: {question_text}")
    if reason:
        print(f"Why low confidence: {reason}")
    suggested_option = exact_option_match(options or [], suggested_answer or "") if options else None
    if options:
        print("Options:")
        for idx, option in enumerate(options, start=1):
            print(f"  {idx}. {option}")
        if suggested_option:
            print(f"Suggested: {suggested_option} (confidence {float(confidence or 0.0):.2f})")
        while True:
            prompt = "Select option number"
            if suggested_option:
                prompt += " or press Enter to accept the suggestion"
            raw = input(f"{prompt}: ").strip()
            if not raw and suggested_option:
                return suggested_option, "user", 1.0
            if raw.isdigit():
                idx = int(raw)
                if 1 <= idx <= len(options):
                    return options[idx - 1], "user", 1.0
            direct_match = exact_option_match(options, raw) if raw else None
            if direct_match:
                return direct_match, "user", 1.0
            print("Invalid selection. Enter an option number or the exact option text.")
    else:
        if suggested_answer:
            print(f"Suggested: {suggested_answer} (confidence {float(confidence or 0.0):.2f})")
        raw = input("Enter answer or press Enter to accept the suggestion: ").strip()
        if raw:
            return raw, "user", 1.0
        if suggested_answer:
            return suggested_answer, "user", 1.0
    return None, None, None


def fill_questionnaire(
    page: Page,
    config: dict,
    resume_text: str,
    job_text: str,
    run_logger=None,
    question_store=None,
) -> bool:
    changed = False
    fields = page.locator("input, textarea, select")
    processed_radio: set[str] = set()
    processed_checkbox: set[str] = set()
    answer_cache: dict[tuple[str, tuple[str, ...]], dict] = {}
    llm_cfg = config.get("llm", {})
    confidence_threshold = float(llm_cfg.get("question_low_confidence_threshold", 0.8))

    def resolve_answer(question_text: str, options: list[str] | None = None) -> dict:
        if not question_text:
            return {"answer": None, "source": None, "confidence": None}
        if _is_non_question_control(question_text, options):
            return {"answer": None, "source": None, "confidence": None}
        key = (question_text, tuple(options or []))
        if key in answer_cache:
            return answer_cache[key]

        answer = None
        source = None
        confidence = None
        reason = ""
        question_issue = ""

        if not answer and question_store:
            memory_row = question_store.lookup_exact(question_text, options)
            if question_store.reusable(memory_row):
                answer = memory_row.get("answer", "").strip()
                source = "memory"
                confidence = 1.0
                if run_logger:
                    run_logger.info(
                        "Employer question reused from verified memory: question=%r options=%s answer=%r",
                        question_text[:250],
                        (options or [])[:8],
                        answer[:200],
                    )

        if not answer:
            qa_memory_table = build_qa_memory_table(config, question_store, question_text, options)
            llm_result = answer_question(
                resume_text,
                job_text,
                question_text,
                config,
                options,
                qa_memory_table=qa_memory_table,
            )
            if llm_result:
                answer = llm_result.get("answer")
                source = "llm"
                confidence = float(llm_result.get("confidence") or 0.0)
                reason = (llm_result.get("reason") or "").strip()
                question_issue = (llm_result.get("question_issue") or "").strip()
            else:
                reason = ""

        if answer and is_placeholder_answer(answer):
            answer = None
            source = None
            confidence = None
            reason = ""

        if options and answer and not exact_option_match(options, answer):
            confidence = 0.0
            reason = reason or "Answer did not map cleanly to one of the available options."

        if (not answer or float(confidence or 0.0) <= confidence_threshold):
            user_answer, user_source, user_confidence = _prompt_user_for_answer(
                question_text,
                options,
                answer,
                confidence,
                reason,
                config,
                run_logger,
            )
            if user_answer:
                answer = user_answer
                source = user_source
                confidence = user_confidence

        result = {
            "answer": answer,
            "source": source,
            "confidence": confidence,
            "reason": reason,
            "question_issue": question_issue,
        }
        answer_cache[key] = result
        return result

    def log_resolution(kind: str, question_text: str, resolution: dict, options: list[str] | None = None) -> None:
        if not run_logger or not question_text:
            return
        answer = resolution.get("answer")
        source = resolution.get("source")
        confidence = resolution.get("confidence")
        reason = resolution.get("reason")
        question_issue = resolution.get("question_issue")
        if answer:
            run_logger.info(
                "Employer question resolved: kind=%s source=%s confidence=%s reason=%r question_issue=%r question=%r options=%s answer=%r",
                kind,
                source or "unknown",
                "" if confidence is None else f"{float(confidence):.2f}",
                (reason or "")[:200],
                (question_issue or "")[:200],
                question_text[:250],
                (options or [])[:8],
                answer[:250],
            )
        else:
            run_logger.info(
                "Employer question unresolved: kind=%s reason=%r question_issue=%r question=%r options=%s",
                kind,
                (reason or "")[:200],
                (question_issue or "")[:200],
                question_text[:250],
                (options or [])[:8],
            )

    def log_application(kind: str, question_text: str, resolution: dict, final_value: str | None, status: str, options: list[str] | None = None) -> None:
        answer = resolution.get("answer") if resolution else None
        source = resolution.get("source") if resolution else None
        confidence = resolution.get("confidence") if resolution else None
        if run_logger and question_text:
            run_logger.info(
                "Employer question applied: kind=%s status=%s source=%s confidence=%s question=%r options=%s resolved_answer=%r final_value=%r",
                kind,
                status,
                source or "",
                "" if confidence is None else f"{float(confidence):.2f}",
                question_text[:250],
                (options or [])[:8],
                (answer or "")[:250],
                (final_value or "")[:250],
            )
        if question_store and question_text and final_value:
            question_store.remember(
                question_text=question_text,
                options=options,
                answer=final_value,
                answered_by=(source or "unknown"),
                confidence=confidence,
                verified=(source == "user"),
            )

    count = fields.count()
    for index in range(count):
        field = fields.nth(index)
        if not _is_visible_enabled(field):
            continue
        tag = (field.evaluate("el => el.tagName.toLowerCase()") or "").lower()
        input_type = (field.get_attribute("type") or "").lower()
        if tag == "input" and input_type in {"hidden", "file", "submit", "button", "image", "search"}:
            continue
        question_text = _get_question_text(field)
        if _is_resume_field(field, question_text) or _is_cover_letter_field(field, question_text):
            continue

        if tag == "select":
            option_locator = field.locator("option")
            options = [(option_locator.nth(i).text_content() or "").strip() for i in range(option_locator.count())]
            resolution = resolve_answer(question_text, options)
            log_resolution("select", question_text, resolution, options)
            answer = resolution.get("answer")
            if not answer:
                log_application("select", question_text, resolution, _selected_option_value(field), "no_answer", options)
                continue
            best = exact_option_match(options, answer)
            if best:
                try:
                    field.select_option(label=best)
                    changed = True
                    log_application("select", question_text, resolution, _selected_option_value(field) or best, "selected", options)
                except Exception:
                    log_application("select", question_text, resolution, _selected_option_value(field), "select_failed", options)
            else:
                log_application("select", question_text, resolution, _selected_option_value(field), "no_option_match", options)
            continue

        if input_type == "radio":
            name = (field.get_attribute("name") or "").strip() or f"radio_{index}"
            if name in processed_radio:
                continue
            processed_radio.add(name)
            radio_group = page.locator(f"input[type='radio'][name='{name}']")
            options: list[str] = []
            radios = []
            for radio_index in range(radio_group.count()):
                radio = radio_group.nth(radio_index)
                label = _get_question_text(radio)
                if not label:
                    label = radio.evaluate(
                        """
                        el => {
                          const wrapper = el.closest('label');
                          return wrapper ? (wrapper.innerText || '').trim() : '';
                        }
                        """
                    ) or ""
                options.append(label)
                radios.append((radio, label))
            group_question = _get_radio_group_question(field) or _get_question_text(field)
            if _looks_like_choice_label(group_question, options):
                group_question = _find_better_group_question(field, options)
            if _is_resume_field(field, group_question) or _is_cover_letter_field(field, group_question) or _is_non_question_control(group_question, options):
                continue
            resolution = resolve_answer(group_question, options)
            log_resolution("radio", group_question, resolution, options)
            answer = resolution.get("answer")
            if not answer:
                log_application("radio", group_question, resolution, "", "no_answer", options)
                continue
            chosen = exact_option_match(options, answer)
            if not chosen:
                log_application("radio", group_question, resolution, "", "no_option_match", options)
                continue
            applied = False
            for radio, label in radios:
                if exact_option_match([label], chosen):
                    try:
                        radio.check()
                        changed = True
                        applied = True
                    except Exception:
                        applied = False
                    break
            log_application("radio", group_question, resolution, chosen, "selected" if applied else "select_failed", options)
            continue

        if input_type == "checkbox":
            name = (field.get_attribute("name") or "").strip() or question_text or f"checkbox_{index}"
            if name in processed_checkbox:
                continue
            processed_checkbox.add(name)
            checkbox_group = page.locator(f"input[type='checkbox'][name='{name}']") if field.get_attribute("name") else page.locator("input[type='checkbox']")
            options: list[str] = []
            checkboxes = []
            for box_index in range(checkbox_group.count()):
                checkbox = checkbox_group.nth(box_index)
                if not _is_visible_enabled(checkbox):
                    continue
                label = _get_question_text(checkbox)
                if not label:
                    label = checkbox.evaluate(
                        """
                        el => {
                          const wrapper = el.closest('label');
                          return wrapper ? (wrapper.innerText || '').trim() : '';
                        }
                        """
                    ) or ""
                options.append(label)
                checkboxes.append((checkbox, label))
            group_question = _get_radio_group_question(field) or _get_question_text(field)
            if _looks_like_choice_label(group_question, options):
                group_question = _find_better_group_question(field, options)
            if _is_resume_field(field, group_question) or _is_cover_letter_field(field, group_question) or _is_non_question_control(group_question, options):
                continue
            resolution = resolve_answer(group_question, options)
            log_resolution("checkbox", group_question, resolution, options)
            answer = resolution.get("answer")
            if not answer:
                log_application("checkbox", group_question, resolution, "", "no_answer", options)
                continue
            desired = [part.strip() for part in answer.split(",") if part.strip()] or [answer]
            selected_labels: list[str] = []
            for checkbox, label in checkboxes:
                if any(exact_option_match([label], desired_item) for desired_item in desired):
                    try:
                        checkbox.check()
                        changed = True
                        if label:
                            selected_labels.append(label)
                    except Exception:
                        pass
            status = "selected" if selected_labels else "no_option_match"
            log_application("checkbox", group_question, resolution, ", ".join(selected_labels), status, options)
            continue

        resolution = resolve_answer(question_text)
        log_resolution("text", question_text, resolution, None)
        answer = resolution.get("answer")
        if not answer:
            log_application("text", question_text, resolution, _current_value(field), "no_answer", None)
            continue
        current = _current_value(field)
        if current:
            log_application("text", question_text, resolution, current, "already_filled", None)
            continue
        try:
            field.fill(answer)
            changed = True
            log_application("text", question_text, resolution, _current_value(field) or answer, "filled", None)
        except Exception:
            try:
                field.evaluate(
                    """
                    (el, value) => {
                      el.value = value;
                      el.dispatchEvent(new Event('input', { bubbles: true }));
                      el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    """,
                    answer,
                )
                changed = True
                log_application("text", question_text, resolution, _current_value(field) or answer, "filled_js", None)
            except Exception:
                log_application("text", question_text, resolution, _current_value(field), "fill_failed", None)
                continue
    return changed
