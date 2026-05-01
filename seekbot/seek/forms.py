import logging
from dataclasses import dataclass, field as dataclass_field
import re
import sys
from typing import Any

from playwright.sync_api import Page

from seekbot.llm import answer_question


@dataclass
class QuestionBlock:
    kind: str
    question_text: str
    options: list[str]
    field: Any
    items: list[tuple[Any, str]] = dataclass_field(default_factory=list)
    allow_multiple: bool = False
    debug_strategy: str = ""
    key: str = ""


def _log_progress(run_logger, message: str, *args) -> None:
    logging.info(message, *args)
    if run_logger:
        run_logger.info(message, *args)


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


def _normalize_option_label(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower()).strip()


def _normalize_option_label_fallback(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9+#. ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def exact_option_match(options: list[str] | None, answer: str | None) -> str | None:
    if not options or not answer:
        return None
    normalized_answer = _normalize_option_label(answer)
    for option in options:
        if _normalize_option_label(option) == normalized_answer:
            return option
    fallback_answer = _normalize_option_label_fallback(answer)
    for option in options:
        if _normalize_option_label_fallback(option) == fallback_answer:
            return option
    return None


def _split_multi_answer(answer: str | None) -> list[str]:
    return [part.strip() for part in str(answer or "").split(",") if part.strip()]


def _answer_maps_to_options(options: list[str] | None, answer: str | None, allow_multiple: bool = False) -> bool:
    if not options or not answer:
        return False
    if allow_multiple:
        parts = _split_multi_answer(answer)
        return bool(parts) and all(exact_option_match(options, part) for part in parts)
    return exact_option_match(options, answer) is not None


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


def _is_sensitive_personal_fact_question(question_text: str) -> bool:
    lowered = normalize_choice(question_text)
    if not lowered:
        return False
    phrases = [
        "security clearance",
        "clearance",
        "citizen",
        "citizenship",
        "permanent resident",
        "residency",
        "visa",
        "work rights",
        "right to work",
        "sponsorship",
        "sponsor",
        "license",
        "licence",
        "police check",
        "working with children",
        "criminal",
        "conviction",
        "bankruptcy",
        "salary",
        "compensation",
        "remuneration",
        "pay rate",
        "hourly rate",
        "daily rate",
        "annual base salary",
        "salary expectation",
    ]
    return any(phrase in lowered for phrase in phrases)


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


def _check_checkbox(field) -> bool:
    try:
        field.check()
        return True
    except Exception:
        pass
    try:
        clicked = field.evaluate(
            """
            el => {
              const wrapper = el.closest('label');
              if (!wrapper) return false;
              wrapper.click();
              return !!el.checked;
            }
            """
        )
        if clicked:
            return True
    except Exception:
        pass
    try:
        return bool(
            field.evaluate(
                """
                el => {
                  el.checked = true;
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  return !!el.checked;
                }
                """
            )
        )
    except Exception:
        return False


def _element_dom_path(field) -> str:
    try:
        return field.evaluate(
            """
            el => {
              const parts = [];
              let cur = el;
              while (cur && cur.nodeType === Node.ELEMENT_NODE && parts.length < 8) {
                let part = cur.tagName.toLowerCase();
                if (cur.id) {
                  part += `#${cur.id}`;
                  parts.unshift(part);
                  break;
                }
                let index = 1;
                let sib = cur;
                while ((sib = sib.previousElementSibling)) {
                  if (sib.tagName === cur.tagName) index += 1;
                }
                part += `:nth-of-type(${index})`;
                parts.unshift(part);
                cur = cur.parentElement;
              }
              return parts.join(' > ');
            }
            """
        ) or ""
    except Exception:
        return ""


def _extract_question_from_container(field, options: list[str] | None = None) -> tuple[str, str]:
    try:
        payload = field.evaluate(
            """
            (el, optionTexts) => {
              const normalize = text => (text || '')
                .toLowerCase()
                .replace(/[^a-z0-9 ]+/g, ' ')
                .replace(/\\s+/g, ' ')
                .trim();
              const optionSet = new Set((optionTexts || []).map(normalize).filter(Boolean));
              const ignoredExact = new Set([
                'yes',
                'no',
                'upload a resume',
                'select a resume',
                'dont include a resume',
                'upload a cover letter',
                'write a cover letter',
                'dont include a cover letter',
                'show strong interest',
              ]);
              const ignoredContains = [
                'show strong interest',
                'make a strong impression',
                'upload a resum',
                'cover letter',
                'coverletter',
              ];

              const chooseLine = lines => {
                for (const line of lines) {
                  const lower = normalize(line);
                  if (!lower || optionSet.has(lower) || ignoredExact.has(lower)) continue;
                  if (ignoredContains.some(token => lower.includes(token))) continue;
                  if (line.includes('?')) return line;
                }
                for (const line of lines) {
                  const lower = normalize(line);
                  if (!lower || optionSet.has(lower) || ignoredExact.has(lower)) continue;
                  if (ignoredContains.some(token => lower.includes(token))) continue;
                  if (line.length >= 18) return line;
                }
                return '';
              };

              let cur = el;
              for (let depth = 0; depth < 6 && cur; depth += 1) {
                const text = (cur.innerText || '').trim();
                if (text) {
                  const lines = text.split('\\n').map(line => line.trim()).filter(Boolean);
                  const chosen = chooseLine(lines);
                  if (chosen) {
                    return {
                      text: chosen,
                      strategy: depth === 0 ? 'container_self' : `container_ancestor_${depth}`,
                    };
                  }
                }
                cur = cur.parentElement;
              }
              return { text: '', strategy: '' };
            }
            """,
            options or [],
        ) or {}
        return _normalize_text(str(payload.get("text", "") or "")), str(payload.get("strategy", "") or "")
    except Exception:
        return "", ""


def _option_group_selector(field, input_type: str) -> str:
    try:
        return field.evaluate(
            """
            (el, desiredType) => {
              const pathFor = node => {
                const parts = [];
                let cur = node;
                while (cur && cur.nodeType === Node.ELEMENT_NODE && parts.length < 8) {
                  let index = 1;
                  let sib = cur;
                  while ((sib = sib.previousElementSibling)) {
                    if (sib.tagName === cur.tagName) index += 1;
                  }
                  parts.unshift(`${cur.tagName.toLowerCase()}:nth-of-type(${index})`);
                  cur = cur.parentElement;
                }
                return parts.join(' > ');
              };

              let cur = el;
              for (let depth = 0; depth < 6 && cur; depth += 1) {
                const matches = cur.querySelectorAll(`input[type="${desiredType}"]`);
                if (matches.length > 1) return pathFor(cur);
                cur = cur.parentElement;
              }
              return pathFor(el);
            }
            """,
            input_type,
        ) or ""
    except Exception:
        return ""


def _extract_block_question(field, options: list[str] | None = None) -> tuple[str, str]:
    direct = _normalize_text(_get_question_text(field))
    if direct and not _looks_like_choice_label(direct, options) and not _is_non_question_control(direct, options):
        return direct, "direct"

    if options:
        group_question = _normalize_text(_get_radio_group_question(field))
        if group_question and not _looks_like_choice_label(group_question, options) and not _is_non_question_control(group_question, options):
            return group_question, "group"

    container_text, strategy = _extract_question_from_container(field, options)
    if container_text and not _looks_like_choice_label(container_text, options) and not _is_non_question_control(container_text, options):
        return container_text, strategy or "container"

    if options:
        fallback = _normalize_text(_find_better_group_question(field, options))
        if fallback and not _is_non_question_control(fallback, options):
            return fallback, "fallback_group"

    return direct or container_text, strategy or "fallback"


def _log_question_block(run_logger, block: QuestionBlock) -> None:
    if not run_logger or not block.question_text:
        return
    run_logger.info(
        "Employer question block: kind=%s strategy=%s key=%s question=%r options=%s",
        block.kind,
        block.debug_strategy,
        block.key[:160],
        block.question_text[:250],
                        block.options,
    )


def _extract_question_blocks(page: Page, run_logger=None) -> list[QuestionBlock]:
    blocks: list[QuestionBlock] = []
    processed_radio: set[str] = set()
    processed_checkbox: set[str] = set()
    processed_custom: set[str] = set()
    fields = page.locator("input, textarea, select, [role='radiogroup'], [role='listbox']")

    count = fields.count()
    for index in range(count):
        field = fields.nth(index)
        if not _is_visible_enabled(field):
            continue

        tag = (field.evaluate("el => el.tagName.toLowerCase()") or "").lower()
        role = (field.get_attribute("role") or "").lower()
        input_type = (field.get_attribute("type") or "").lower()

        if role in {"radiogroup", "listbox"}:
            container_key = _element_dom_path(field) or f"{role}_{index}"
            if container_key in processed_custom:
                continue
            processed_custom.add(container_key)
            try:
                if field.locator("input, textarea, select").count():
                    continue
            except Exception:
                pass

            if role == "radiogroup":
                option_locator = field.locator("[role='radio']")
                items: list[tuple[Any, str]] = []
                options: list[str] = []
                for option_index in range(option_locator.count()):
                    option = option_locator.nth(option_index)
                    if not _is_visible_enabled(option):
                        continue
                    label = _normalize_text(
                        (option.get_attribute("aria-label") or "")
                        or (option.get_attribute("innerText") or "")
                    )
                    if not label:
                        try:
                            label = _normalize_text(option.inner_text() or "")
                        except Exception:
                            label = ""
                    if label:
                        items.append((option, label))
                        options.append(label)
                if not items:
                    continue
                question_text, strategy = _extract_block_question(field, options)
                block = QuestionBlock(
                    kind="aria_radio",
                    question_text=question_text,
                    options=options,
                    field=field,
                    items=items,
                    debug_strategy=strategy or "aria_radiogroup",
                    key=container_key,
                )
                _log_question_block(run_logger, block)
                blocks.append(block)
                continue

            if role == "listbox":
                option_locator = field.locator("[role='option']")
                items = []
                options = []
                for option_index in range(option_locator.count()):
                    option = option_locator.nth(option_index)
                    try:
                        label = _normalize_text(option.inner_text() or "")
                    except Exception:
                        label = ""
                    if label:
                        items.append((option, label))
                        options.append(label)
                if not items:
                    continue
                is_multi_select = False
                try:
                    is_multi_select = (field.get_attribute("aria-multiselectable") or "").lower() == "true"
                except Exception:
                    is_multi_select = False
                question_text, strategy = _extract_block_question(field, options)
                block = QuestionBlock(
                    kind="aria_listbox",
                    question_text=question_text,
                    options=options,
                    field=field,
                    items=items,
                    allow_multiple=is_multi_select,
                    debug_strategy=strategy or "aria_listbox",
                    key=container_key,
                )
                _log_question_block(run_logger, block)
                blocks.append(block)
                continue

        if tag == "input" and input_type in {"hidden", "file", "submit", "button", "image", "search"}:
            continue

        raw_question = _get_question_text(field)
        if _is_resume_field(field, raw_question) or _is_cover_letter_field(field, raw_question):
            continue

        if tag == "select":
            option_locator = field.locator("option")
            options = [(option_locator.nth(i).text_content() or "").strip() for i in range(option_locator.count())]
            is_multi_select = False
            try:
                is_multi_select = bool(field.evaluate("el => !!el.multiple"))
            except Exception:
                is_multi_select = False
            question_text, strategy = _extract_block_question(field, options)
            block = QuestionBlock(
                kind="select",
                question_text=question_text,
                options=options,
                field=field,
                allow_multiple=is_multi_select,
                debug_strategy=strategy or "select",
                key=_element_dom_path(field),
            )
            _log_question_block(run_logger, block)
            blocks.append(block)
            continue

        if input_type == "radio":
            name = (field.get_attribute("name") or "").strip()
            group_key = name or _option_group_selector(field, "radio") or f"radio_{index}"
            if group_key in processed_radio:
                continue
            processed_radio.add(group_key)
            if name:
                radio_group = page.locator(f"input[type='radio'][name='{name}']")
            else:
                radio_group = page.locator(group_key).locator("input[type='radio']")
            items = []
            options = []
            for radio_index in range(radio_group.count()):
                radio = radio_group.nth(radio_index)
                if not _is_visible_enabled(radio):
                    continue
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
                label = _normalize_text(label)
                if label:
                    options.append(label)
                items.append((radio, label))
            question_text, strategy = _extract_block_question(field, options)
            block = QuestionBlock(
                kind="radio",
                question_text=question_text,
                options=options,
                field=field,
                items=items,
                debug_strategy=strategy or "radio",
                key=f"radio:{group_key}",
            )
            _log_question_block(run_logger, block)
            blocks.append(block)
            continue

        if input_type == "checkbox":
            name = (field.get_attribute("name") or "").strip()
            group_key = name or _option_group_selector(field, "checkbox") or raw_question or f"checkbox_{index}"
            if group_key in processed_checkbox:
                continue
            processed_checkbox.add(group_key)
            checkbox_group = page.locator(f"input[type='checkbox'][name='{name}']") if name else page.locator(group_key).locator("input[type='checkbox']")
            items = []
            options = []
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
                label = _normalize_text(label)
                if label:
                    options.append(label)
                items.append((checkbox, label))
            question_text, strategy = _extract_block_question(field, options)
            block = QuestionBlock(
                kind="checkbox",
                question_text=question_text,
                options=options,
                field=field,
                items=items,
                allow_multiple=True,
                debug_strategy=strategy or "checkbox",
                key=f"checkbox:{group_key}",
            )
            _log_question_block(run_logger, block)
            blocks.append(block)
            continue

        question_text, strategy = _extract_block_question(field, None)
        block = QuestionBlock(
            kind="text",
            question_text=question_text,
            options=[],
            field=field,
            debug_strategy=strategy or "text",
            key=_element_dom_path(field),
        )
        _log_question_block(run_logger, block)
        blocks.append(block)

    return blocks


def _build_qa_memory_table(question_store, question_text: str, options: list[str] | None) -> str:
    prior = question_store.format_prompt_context(question_text, options) if question_store else "N/A"
    if prior != "N/A":
        return "\n".join(["VERIFIED_PRIOR_QUESTIONNAIRE_QA", prior])
    return "N/A"


def _prompt_user_for_answer(
    question_text: str,
    options: list[str] | None,
    suggested_answer: str | None,
    confidence: float | None,
    reason: str | None,
    config: dict,
    run_logger=None,
    allow_multiple: bool = False,
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
            options or [],
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
        suggested_display = suggested_answer if allow_multiple else suggested_option
        if suggested_display:
            print(f"Suggested: {suggested_display} (confidence {float(confidence or 0.0):.2f})")
        while True:
            if allow_multiple:
                prompt = "Select option numbers (comma-separated) or exact option text"
            else:
                prompt = "Select option number"
            if suggested_display:
                prompt += " or press Enter to accept the suggestion"
            raw = input(f"{prompt}: ").strip()
            if not raw and suggested_display:
                return suggested_display, "user", 1.0
            if allow_multiple and raw:
                tokens = [t.strip() for t in raw.split(",") if t.strip()]
                matched: list[str] = []
                valid = True
                for token in tokens:
                    if token.isdigit():
                        idx = int(token)
                        if 1 <= idx <= len(options):
                            matched.append(options[idx - 1])
                            continue
                    direct = exact_option_match(options, token)
                    if direct:
                        matched.append(direct)
                        continue
                    valid = False
                    break
                if valid and matched:
                    seen: set[str] = set()
                    unique = [m for m in matched if not (m in seen or seen.add(m))]
                    return ", ".join(unique), "user", 1.0
            elif raw.isdigit():
                idx = int(raw)
                if 1 <= idx <= len(options):
                    return options[idx - 1], "user", 1.0
            direct_match = exact_option_match(options, raw) if raw and not allow_multiple else None
            if direct_match:
                return direct_match, "user", 1.0
            if allow_multiple:
                print("Invalid selection. Enter comma-separated option numbers or exact option text.")
            else:
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
    run_logger=None,
    question_store=None,
) -> bool:
    changed = False
    answer_cache: dict[tuple[str, tuple[str, ...], bool], dict] = {}
    llm_cfg = config.get("llm", {})
    confidence_threshold = float(llm_cfg.get("question_low_confidence_threshold", 0.85))

    def resolve_answer(question_text: str, options: list[str] | None = None, allow_multiple: bool = False) -> dict:
        if not question_text:
            return {"answer": None, "source": None, "confidence": None}
        if _is_non_question_control(question_text, options):
            return {"answer": None, "source": None, "confidence": None}
        key = (question_text, tuple(options or []), allow_multiple)
        if key in answer_cache:
            return answer_cache[key]

        answer = None
        source = None
        confidence = None
        reason = ""
        question_issue = ""
        requires_confirmation = False

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
                        options or [],
                        answer[:200],
                    )

        if not answer and question_store and hasattr(question_store, "lookup_similar_verified"):
            similar_row = question_store.lookup_similar_verified(question_text, options)
            if similar_row:
                similar_answer = str(similar_row.get("answer", "") or "").strip()
                similar_question = str(similar_row.get("question_text", "") or "").strip()
                similar_confidence = float(similar_row.get("similarity") or 0.0)
                if similar_answer and similar_confidence > confidence_threshold:
                    answer = similar_answer
                    source = "memory_similar"
                    confidence = similar_confidence
                    reason = f"Reused verified answer from similar question: {similar_question[:160]}"
                else:
                    user_answer, user_source, user_confidence = _prompt_user_for_answer(
                        question_text,
                        options,
                        similar_answer,
                        similar_confidence,
                        f"Verified prior answer from similar question: {similar_question[:160]}",
                        config,
                        run_logger,
                        allow_multiple=allow_multiple,
                    )
                    if user_answer:
                        answer = user_answer
                        source = user_source
                        confidence = user_confidence
                        reason = "Confirmed from similar verified memory."

        if not answer:
            qa_memory_table = _build_qa_memory_table(question_store, question_text, options)
            llm_result = answer_question(
                resume_text,
                question_text,
                config,
                options,
                qa_memory_table=qa_memory_table,
                allow_multiple=allow_multiple,
            )
            if llm_result:
                answer = llm_result.get("answer")
                source = "llm"
                confidence = float(llm_result.get("confidence") or 0.0)
                reason = (llm_result.get("reason") or "").strip()
                question_issue = (llm_result.get("question_issue") or "").strip()
                if answer and _is_sensitive_personal_fact_question(question_text):
                    confidence = min(float(confidence or 0.0), confidence_threshold)
                    requires_confirmation = True
                    if not reason:
                        reason = "Sensitive personal question requires user confirmation without verified memory."
            else:
                reason = ""

        if answer and is_placeholder_answer(answer):
            answer = None
            source = None
            confidence = None
            reason = ""

        if options and answer and not _answer_maps_to_options(options, answer, allow_multiple=allow_multiple):
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
                allow_multiple=allow_multiple,
            )
            if user_answer:
                answer = user_answer
                source = user_source
                confidence = user_confidence
            elif requires_confirmation:
                if run_logger:
                    run_logger.info(
                        "Sensitive question answer dropped: question=%r suggested_answer=%r confidence=%s reason=%r",
                        question_text[:250],
                        (answer or "")[:200],
                        "" if confidence is None else f"{float(confidence):.2f}",
                        (reason or "")[:200],
                    )
                answer = None
                source = None
                confidence = None

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
                options or [],
                answer[:250],
            )
        else:
            run_logger.info(
                "Employer question unresolved: kind=%s reason=%r question_issue=%r question=%r options=%s",
                kind,
                (reason or "")[:200],
                (question_issue or "")[:200],
                question_text[:250],
                options or [],
            )

    def log_application(kind: str, question_text: str, resolution: dict, final_value: str | None, status: str, options: list[str] | None = None) -> None:
        answer = resolution.get("answer") if resolution else None
        source = resolution.get("source") if resolution else None
        confidence = resolution.get("confidence") if resolution else None
        persistable_statuses = {"selected", "filled", "filled_js"}
        if run_logger and question_text:
            run_logger.info(
                "Employer question applied: kind=%s status=%s source=%s confidence=%s question=%r options=%s resolved_answer=%r final_value=%r",
                kind,
                status,
                source or "",
                "" if confidence is None else f"{float(confidence):.2f}",
                question_text[:250],
                options or [],
                (answer or "")[:250],
                (final_value or "")[:250],
            )
        if question_store and question_text and final_value and status in persistable_statuses and source in {"user", "memory", "memory_similar", "llm"}:
            question_store.remember(
                question_text=question_text,
                options=options,
                answer=final_value,
                answered_by=(source or "unknown"),
                confidence=confidence,
                verified=(source in {"user", "memory", "memory_similar"}),
            )

    blocks = _extract_question_blocks(page, run_logger)
    usable_blocks: list[QuestionBlock] = []
    for block in blocks:
        field = block.field
        question_text = block.question_text
        options = block.options
        if not question_text:
            continue
        if _is_resume_field(field, question_text) or _is_cover_letter_field(field, question_text):
            continue
        if _is_non_question_control(question_text, options):
            continue
        usable_blocks.append(block)

    if usable_blocks:
        _log_progress(run_logger, "Application stage: questionnaire page detected questions=%d", len(usable_blocks))
    else:
        _log_progress(run_logger, "Application stage: no questionnaire questions detected on current page")

    for index, block in enumerate(usable_blocks, start=1):
        field = block.field
        question_text = block.question_text
        options = block.options
        _log_progress(
            run_logger,
            "Application stage: answering question %d/%d kind=%s question=%r",
            index,
            len(usable_blocks),
            block.kind,
            question_text[:160],
        )

        if block.kind == "select":
            resolution = resolve_answer(question_text, options, allow_multiple=block.allow_multiple)
            log_resolution("select", question_text, resolution, options)
            answer = resolution.get("answer")
            if not answer:
                log_application("select", question_text, resolution, _selected_option_value(field), "no_answer", options)
                continue
            if block.allow_multiple:
                desired = _split_multi_answer(answer) or [answer]
            else:
                desired = [answer]
            matched = []
            for item in desired:
                best = exact_option_match(options, item)
                if best and best not in matched:
                    matched.append(best)
            if matched:
                try:
                    if block.allow_multiple:
                        field.select_option(label=matched)
                    else:
                        field.select_option(label=matched[0])
                    changed = True
                    final_value = ", ".join(matched) if block.allow_multiple else (_selected_option_value(field) or matched[0])
                    log_application("select", question_text, resolution, final_value, "selected", options)
                except Exception:
                    log_application("select", question_text, resolution, _selected_option_value(field), "select_failed", options)
            else:
                log_application("select", question_text, resolution, _selected_option_value(field), "no_option_match", options)
            continue

        if block.kind == "radio":
            resolution = resolve_answer(question_text, options)
            log_resolution("radio", question_text, resolution, options)
            answer = resolution.get("answer")
            if not answer:
                log_application("radio", question_text, resolution, "", "no_answer", options)
                continue
            chosen = exact_option_match(options, answer)
            if not chosen:
                log_application("radio", question_text, resolution, "", "no_option_match", options)
                continue
            applied = False
            for radio, label in block.items:
                if exact_option_match([label], chosen):
                    try:
                        radio.check()
                        changed = True
                        applied = True
                    except Exception:
                        applied = False
                    break
            log_application("radio", question_text, resolution, chosen, "selected" if applied else "select_failed", options)
            continue

        if block.kind == "checkbox":
            resolution = resolve_answer(question_text, options, allow_multiple=True)
            log_resolution("checkbox", question_text, resolution, options)
            answer = resolution.get("answer")
            if not answer:
                log_application("checkbox", question_text, resolution, "", "no_answer", options)
                continue
            desired = _split_multi_answer(answer) or [answer]
            selected_labels: list[str] = []
            matched_label = False
            for checkbox, label in block.items:
                if any(exact_option_match([label], desired_item) for desired_item in desired):
                    matched_label = True
                    if _check_checkbox(checkbox):
                        changed = True
                        if label:
                            selected_labels.append(label)
            status = "selected" if selected_labels else ("select_failed" if matched_label else "no_option_match")
            log_application("checkbox", question_text, resolution, ", ".join(selected_labels), status, options)
            continue

        if block.kind == "aria_radio":
            resolution = resolve_answer(question_text, options)
            log_resolution("aria_radio", question_text, resolution, options)
            answer = resolution.get("answer")
            if not answer:
                log_application("aria_radio", question_text, resolution, "", "no_answer", options)
                continue
            chosen = exact_option_match(options, answer)
            if not chosen:
                log_application("aria_radio", question_text, resolution, "", "no_option_match", options)
                continue
            applied = False
            for option, label in block.items:
                if exact_option_match([label], chosen):
                    try:
                        option.click(force=True)
                        changed = True
                        applied = True
                    except Exception:
                        applied = False
                    break
            log_application("aria_radio", question_text, resolution, chosen, "selected" if applied else "select_failed", options)
            continue

        if block.kind == "aria_listbox":
            resolution = resolve_answer(question_text, options, allow_multiple=block.allow_multiple)
            log_resolution("aria_listbox", question_text, resolution, options)
            answer = resolution.get("answer")
            if not answer:
                log_application("aria_listbox", question_text, resolution, "", "no_answer", options)
                continue
            desired = _split_multi_answer(answer) or [answer]
            selected_labels: list[str] = []
            matched_label = False
            for option, label in block.items:
                if any(exact_option_match([label], desired_item) for desired_item in desired):
                    matched_label = True
                    try:
                        option.click(force=True)
                        changed = True
                        selected_labels.append(label)
                    except Exception:
                        continue
            status = "selected" if selected_labels else ("select_failed" if matched_label else "no_option_match")
            log_application("aria_listbox", question_text, resolution, ", ".join(selected_labels), status, options)
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
    _log_progress(
        run_logger,
        "Application stage: questionnaire page complete questions=%d changed=%s",
        len(usable_blocks),
        changed,
    )
    return changed
