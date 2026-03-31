import logging
import os
import re
import hashlib
from datetime import datetime

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from seekbot.llm import generate_cover_letter
from seekbot.domain import JobDetails, ResumeChoice
from seekbot.seek.forms import fill_questionnaire
from seekbot.seek.search import is_seek_domain_url


class ApplicationFlow:
    def __init__(self, page: Page, config: dict, run_logger=None, action_logger=None, question_store=None):
        self.page = page
        self.config = config
        self.run_logger = run_logger
        self.action_logger = action_logger
        self.question_store = question_store

    def _log_action(self, message: str) -> None:
        if self.action_logger:
            self.action_logger.info(message)

    def _body_text(self) -> str:
        try:
            return self.page.locator("body").inner_text(timeout=4000)
        except Exception:
            return ""

    def already_applied_notice(self) -> bool:
        return "you applied on" in self._body_text().lower()

    def _submit_success_url(self, url: str | None = None) -> bool:
        current = (url or self.page.url or "").lower()
        if not is_seek_domain_url(current):
            return False
        return "/apply/success" in current

    def _page_signature(self) -> tuple[str, str, str]:
        try:
            title = self.page.title()
        except Exception:
            title = ""
        body = self._body_text()
        digest = hashlib.sha1(re.sub(r"\s+", " ", body).encode("utf-8")).hexdigest()[:12] if body else ""
        return self.page.url, title, digest

    def _button_locators(self, kind: str):
        if kind == "continue":
            return [
                ("testid_continue", self.page.locator("button[data-testid='continue-button']")),
                ("testid_review", self.page.locator("button[data-testid='review-submit-button']")),
                ("role_continue", self.page.get_by_role("button", name=re.compile(r"continue|next|review and submit", re.I))),
                ("text_continue", self.page.locator("button, [role='button']").filter(has_text=re.compile(r"continue|next|review and submit", re.I))),
            ]
        if kind == "submit":
            return [
                ("testid_submit", self.page.locator("button[data-testid='review-submit-application']")),
                ("role_submit", self.page.get_by_role("button", name=re.compile(r"^submit(?: application)?$", re.I))),
                ("text_submit", self.page.locator("button, [role='button']").filter(has_text=re.compile(r"^submit(?: application)?$", re.I))),
            ]
        return []

    def _click_button(self, kind: str) -> bool:
        last_error = None
        for strategy, locator in self._button_locators(kind):
            for index in range(locator.count()):
                button = locator.nth(index)
                try:
                    if not button.is_visible() or not button.is_enabled():
                        continue
                    try:
                        label = (button.inner_text(timeout=500) or "").strip()
                    except Exception:
                        label = (button.get_attribute("aria-label") or "").strip()
                    button.scroll_into_view_if_needed()
                    button.click(force=True, timeout=3000)
                    self.page.wait_for_timeout(600)
                    self._log_action(f"button_click:{kind}:{strategy}:{label[:80]}")
                    if self.run_logger:
                        self.run_logger.info("Button click: kind=%s strategy=%s label=%r", kind, strategy, label[:120])
                    return True
                except Exception as exc:
                    last_error = exc
                    continue
        if self.run_logger and last_error is not None:
            self.run_logger.info("Button click failed: kind=%s error=%s", kind, last_error)
        return False

    def _visible_button_present(self, kind: str) -> bool:
        for _, locator in self._button_locators(kind):
            try:
                count = min(locator.count(), 5)
            except Exception:
                count = 0
            for index in range(count):
                button = locator.nth(index)
                try:
                    if button.is_visible() and button.is_enabled():
                        return True
                except Exception:
                    continue
        return False

    def _continue_present(self) -> bool:
        return self._visible_button_present("continue")

    def _submit_present(self) -> bool:
        return self._visible_button_present("submit")

    def _intro_resume_present(self) -> bool:
        patterns = [r"upload a resum", r"select a resum", r"don't include a resum"]
        radio_count = sum(self.page.get_by_role("radio", name=re.compile(pattern, re.I)).count() for pattern in patterns)
        label_count = sum(self.page.locator("label").filter(has_text=re.compile(pattern, re.I)).count() for pattern in patterns)
        return (radio_count + label_count) > 0

    def _intro_cover_letter_present(self) -> bool:
        patterns = [r"upload a cover letter", r"write a cover letter", r"don't include a cover letter"]
        radio_count = sum(self.page.get_by_role("radio", name=re.compile(pattern, re.I)).count() for pattern in patterns)
        label_count = sum(self.page.locator("label").filter(has_text=re.compile(pattern, re.I)).count() for pattern in patterns)
        return (radio_count + label_count) > 0

    def _is_intro_page(self) -> bool:
        return self._intro_resume_present() or self._intro_cover_letter_present()

    def _is_final_review_page(self) -> bool:
        return self._submit_present() and not self._is_intro_page()

    def _accept_review_consents(self) -> int:
        accepted = 0
        locator = self.page.locator("input[type='checkbox'], [role='checkbox']")
        seen: set[str] = set()
        for index in range(locator.count()):
            field = locator.nth(index)
            try:
                if not field.is_visible() or not field.is_enabled():
                    continue
                payload = field.evaluate(
                    """
                    el => {
                      const wrapper = el.closest('label');
                      const labelledBy = (el.getAttribute('aria-labelledby') || '').trim();
                      const labelledText = labelledBy
                        ? labelledBy.split(/\\s+/).map(id => document.getElementById(id)).filter(Boolean).map(node => (node.innerText || '').trim()).filter(Boolean).join(' ')
                        : '';
                      const text = ((el.labels && el.labels[0] && el.labels[0].innerText) || labelledText || (wrapper && wrapper.innerText) || (el.parentElement && el.parentElement.innerText) || '').trim();
                      const checked = el.tagName.toLowerCase() === 'input' ? !!el.checked : (el.getAttribute('aria-checked') || '').toLowerCase() === 'true';
                      return { text, checked };
                    }
                    """
                ) or {}
                question_text = re.sub(r"\s+", " ", str(payload.get("text", "")).strip())
                lowered = question_text.lower()
                if not lowered or lowered in seen:
                    continue
                if "show strong interest" in lowered or "make a strong impression" in lowered:
                    continue
                if not any(token in lowered for token in ["agree", "consent", "privacy policy", "terms", "collection notice", "privacy notice"]):
                    continue
                seen.add(lowered)
                if payload.get("checked"):
                    continue
                if (field.evaluate("el => el.tagName.toLowerCase()") or "").lower() == "input":
                    field.check(force=True)
                else:
                    field.click(force=True)
                self.page.wait_for_timeout(250)
                accepted += 1
                self._log_action(f"review_consent:{question_text[:120]}")
                if self.run_logger:
                    self.run_logger.info("Review consent accepted: question=%r", question_text[:250])
            except Exception as exc:
                if self.run_logger:
                    self.run_logger.info("Review consent acceptance failed: error=%s", exc)
        return accepted

    def _target_resume_names(self, resume_path: str) -> list[str]:
        base = os.path.basename(resume_path).strip().lower()
        stem, _ = os.path.splitext(base)
        names = [base, stem, base.replace("_", " "), stem.replace("_", " ")]
        return sorted({re.sub(r"[^a-z0-9]+", " ", item).strip() for item in names if item})

    def _parse_visible_date(self, text: str):
        patterns = [
            (r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", "%d/%m/%Y"),
            (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", "%Y-%m-%d"),
            (r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b", "%d %B %Y"),
            (r"\b(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\b", "%d %b %Y"),
        ]
        for pattern, fmt in patterns:
            match = re.search(pattern, text or "")
            if not match:
                continue
            value = match.group(0)
            if fmt == "%d/%m/%Y":
                parts = value.split("/")
                if len(parts) == 3 and len(parts[2]) == 2:
                    value = f"{parts[0]}/{parts[1]}/20{parts[2]}"
            try:
                return datetime.strptime(value, fmt).date()
            except Exception:
                continue
        return None

    def _local_resume_date(self, resume_path: str):
        try:
            return datetime.fromtimestamp(os.path.getmtime(resume_path)).date()
        except Exception:
            return None

    def _resume_matches(self, text: str, targets: list[str]) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
        return any(target and target in normalized for target in targets)

    def _resume_select_locator(self):
        selects = self.page.locator("select")
        for index in range(selects.count()):
            select = selects.nth(index)
            try:
                options_text = " ".join(
                    (select.locator("option").nth(i).text_content() or "").strip()
                    for i in range(select.locator("option").count())
                ).lower()
            except Exception:
                options_text = ""
            if "resum" in options_text:
                return select
        return None

    def _resume_option_matches(self, option_text: str, resume_path: str) -> bool:
        return self._resume_matches(option_text, self._target_resume_names(resume_path))

    def _set_radio_choice(self, phrase: str) -> bool:
        pattern = re.compile(phrase, re.I)
        radio = self.page.get_by_role("radio", name=pattern)
        if radio.count():
            try:
                if not radio.first.is_checked():
                    radio.first.check(force=True)
                self.page.wait_for_timeout(250)
                self._log_action(f"radio_select:{phrase}")
                return True
            except Exception:
                pass

        label = self.page.locator("label").filter(has_text=pattern)
        if label.count():
            try:
                label.first.click(force=True)
                self.page.wait_for_timeout(250)
                self._log_action(f"label_click:{phrase}")
                return True
            except Exception:
                pass

        field = self.page.get_by_label(pattern)
        if field.count():
            try:
                field.first.check(force=True)
                self.page.wait_for_timeout(250)
                self._log_action(f"label_check:{phrase}")
                return True
            except Exception:
                pass
        return False

    def _click_text(self, phrase: str) -> bool:
        locator = self.page.get_by_role("button", name=re.compile(phrase, re.I))
        if locator.count():
            locator.first.click()
            self.page.wait_for_timeout(300)
            self._log_action(f"text_button_click:{phrase}")
            return True
        locator = self.page.get_by_text(re.compile(phrase, re.I))
        if locator.count():
            locator.first.click(force=True)
            self.page.wait_for_timeout(300)
            self._log_action(f"text_click:{phrase}")
            return True
        return False

    def _visible_texts_matching(self, pattern: str) -> list[str]:
        matcher = re.compile(pattern, re.I)
        results: list[str] = []
        locator = self.page.locator("body *")
        count = min(locator.count(), 600)
        for index in range(count):
            node = locator.nth(index)
            try:
                if not node.is_visible():
                    continue
                text = (node.inner_text(timeout=200) or "").strip()
            except Exception:
                continue
            if text and matcher.search(text) and text not in results:
                results.append(text)
        return results

    def _resume_upload_button(self):
        buttons = [
            self.page.get_by_role("button", name=re.compile(r"^upload$", re.I)),
            self.page.get_by_role("button", name=re.compile(r"upload", re.I)),
            self.page.get_by_text(re.compile(r"^upload$", re.I)),
        ]
        for locator in buttons:
            if locator.count():
                return locator.first
        return None

    def _resume_limit_dialog(self):
        dialogs = self.page.locator("[role='dialog'], dialog")
        for index in range(dialogs.count()):
            dialog = dialogs.nth(index)
            try:
                if not dialog.is_visible():
                    continue
                text = (dialog.inner_text(timeout=500) or "").strip().lower()
            except Exception:
                continue
            if "resum" in text and "limit reached" in text:
                return dialog
        return None

    def _choose_resume_option_in_scope(self, scope, option_text: str) -> bool:
        selects = scope.locator("select")
        for index in range(selects.count()):
            select = selects.nth(index)
            try:
                select.select_option(label=option_text)
                self.page.wait_for_timeout(300)
                return True
            except Exception:
                continue

        triggers = scope.locator("[role='combobox'], [aria-haspopup='listbox']")
        if triggers.count():
            try:
                triggers.first.click(force=True)
                self.page.wait_for_timeout(200)
            except Exception:
                pass
        option = scope.get_by_text(re.compile(re.escape(option_text), re.I))
        if option.count():
            try:
                option.first.click(force=True)
                self.page.wait_for_timeout(300)
                return True
            except Exception:
                return False
        return False

    def _wait_for_resume_limit_resolution(self) -> bool:
        try:
            dialog = self._resume_limit_dialog()
            if dialog is None:
                return True
            dialog.wait_for(state="hidden", timeout=4000)
            return True
        except Exception:
            return self._resume_limit_dialog() is None

    def _replace_resume_from_limit_dialog(self, resume_path: str, option_text: str) -> bool:
        dialog = self._resume_limit_dialog()
        if dialog is None:
            return True
        if self.run_logger:
            self.run_logger.info(
                "Resume limit dialog: target=%s delete_option=%s",
                os.path.basename(resume_path),
                option_text,
            )
        if not self._choose_resume_option_in_scope(dialog, option_text):
            return False
        if self._wait_for_resume_limit_resolution():
            return True

        for pattern in [r"delete", r"remove", r"replace", r"continue", r"done"]:
            button = dialog.get_by_role("button", name=re.compile(pattern, re.I))
            if button.count():
                try:
                    button.first.click(force=True)
                    self.page.wait_for_timeout(300)
                    if self._wait_for_resume_limit_resolution():
                        return True
                except Exception:
                    continue
        return self._resume_limit_dialog() is None

    def _upload_resume_file(self, resume_path: str) -> tuple[bool, str]:
        if not self._set_radio_choice("Upload a resum"):
            return False, "resume_upload_mode_unavailable"

        upload_button = self._resume_upload_button()
        file_inputs = self.page.locator("input[type='file']")
        if self.run_logger:
            self.run_logger.info(
                "Resume upload controls: button=%s file_inputs=%d",
                bool(upload_button),
                file_inputs.count(),
            )

        uploaded = False
        if file_inputs.count():
            try:
                file_inputs.first.set_input_files(resume_path)
                uploaded = True
                self._log_action(f"resume_file_input:{os.path.basename(resume_path)}")
            except Exception:
                uploaded = False
        if not uploaded and upload_button:
            try:
                with self.page.expect_file_chooser(timeout=3000) as chooser_info:
                    upload_button.click(force=True)
                chooser_info.value.set_files(resume_path)
                uploaded = True
                self._log_action(f"resume_file_chooser:{os.path.basename(resume_path)}")
            except PlaywrightTimeoutError:
                uploaded = False
            except Exception:
                uploaded = False
        if not uploaded:
            return False, "resume_upload_input_missing"

        self.page.wait_for_timeout(800)
        dialog = self._resume_limit_dialog()
        if dialog is not None:
            return False, "resume_limit_reached"
        return True, "resume_upload_submitted"

    def _ensure_resume(self, resume_path: str) -> tuple[bool, str]:
        targets = self._target_resume_names(resume_path)
        local_date = self._local_resume_date(resume_path)
        select = self._resume_select_locator()
        selected_text = ""
        stale_existing = ""
        if select is not None:
            options = select.locator("option")
            matched_options = []
            for index in range(options.count()):
                option_text = (options.nth(index).text_content() or "").strip()
                if self._resume_matches(option_text, targets):
                    matched_options.append(option_text)
            if self.run_logger:
                self.run_logger.info(
                    "Resume options: target=%s local_date=%s matches=%s",
                    os.path.basename(resume_path),
                    local_date,
                    matched_options,
                )
            if matched_options:
                selected_text = matched_options[0]
                remote_date = self._parse_visible_date(selected_text)
                if remote_date and local_date and remote_date >= local_date:
                    if not self._set_radio_choice("Select a resum"):
                        return False, "resume_select_mode_unavailable"
                    if not self._choose_resume_option_in_scope(self.page, selected_text):
                        try:
                            select.select_option(label=selected_text)
                        except Exception:
                            return False, "resume_existing_select_failed"
                    return self._verify_resume(resume_path), "selected_existing_current"
                stale_existing = selected_text

        upload_ok, upload_reason = self._upload_resume_file(resume_path)
        if not upload_ok and upload_reason == "resume_limit_reached" and stale_existing:
            if not self._replace_resume_from_limit_dialog(resume_path, stale_existing):
                return False, "resume_limit_delete_failed"
            upload_ok, upload_reason = self._upload_resume_file(resume_path)
        if not upload_ok:
            return False, upload_reason
        if self._verify_resume(resume_path):
            return True, "uploaded_resume"
        visible_matches = self._visible_texts_matching(re.escape(os.path.basename(resume_path)))
        stem_matches = self._visible_texts_matching(re.escape(os.path.splitext(os.path.basename(resume_path))[0]))
        if self.run_logger:
            self.run_logger.info(
                "Resume upload verification fallback: basename_matches=%s stem_matches=%s",
                visible_matches[:5],
                stem_matches[:5],
            )
        if visible_matches or stem_matches:
            return True, "uploaded_resume_visible"
        return False, "resume_upload_not_verified"

    def _verify_resume(self, resume_path: str) -> bool:
        select = self._resume_select_locator()
        if select is None:
            if self.run_logger:
                self.run_logger.info("Resume verification: no resume select found for target=%s", os.path.basename(resume_path))
            return False
        current = select.input_value()
        option_text = ""
        options = select.locator("option")
        for index in range(options.count()):
            option = options.nth(index)
            if option.get_attribute("value") == current:
                option_text = (option.text_content() or "").strip()
                break
        option_text = option_text or current
        local_date = self._local_resume_date(resume_path)
        remote_date = self._parse_visible_date(option_text)
        matches = self._resume_matches(option_text, self._target_resume_names(resume_path))
        date_ok = not (remote_date and local_date) or remote_date >= local_date
        if self.run_logger:
            self.run_logger.info(
                "Resume verification: current=%r target=%s matches=%s local_date=%s remote_date=%s date_ok=%s",
                option_text[:160],
                os.path.basename(resume_path),
                matches,
                local_date,
                remote_date,
                date_ok,
            )
        return matches and date_ok

    def _cover_letter_locator(self):
        self._set_radio_choice("Write a cover letter")
        candidates = self.page.locator("textarea, [contenteditable='true']")
        for index in range(candidates.count()):
            field = candidates.nth(index)
            descriptor = " ".join(
                filter(
                    None,
                    [
                        field.get_attribute("id") or "",
                        field.get_attribute("name") or "",
                        field.get_attribute("data-testid") or "",
                        field.get_attribute("aria-label") or "",
                        field.get_attribute("placeholder") or "",
                    ],
                )
            ).lower()
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
                )
            except Exception:
                ancestor_text = ""
            descriptor = f"{descriptor} {ancestor_text}".lower()
            if "coverletter" in descriptor or "cover letter" in descriptor:
                return field
        return None

    def _ensure_cover_letter(self, cover_letter_text: str | None) -> tuple[bool, str]:
        if not cover_letter_text:
            return False, "cover_letter_missing"
        field = self._cover_letter_locator()
        if field is None:
            if self.run_logger:
                self.run_logger.info("Cover letter verification: no matching field found")
            return False, "cover_letter_field_missing"
        try:
            field.fill(cover_letter_text)
            return self._verify_cover_letter(cover_letter_text), "cover_letter_filled"
        except Exception:
            try:
                field.click(force=True)
                self.page.keyboard.press("Meta+A")
                self.page.keyboard.press("Control+A")
                self.page.keyboard.insert_text(cover_letter_text)
                return self._verify_cover_letter(cover_letter_text), "cover_letter_filled_keyboard"
            except Exception:
                return False, "cover_letter_fill_failed"

    def _verify_cover_letter(self, cover_letter_text: str | None) -> bool:
        if not cover_letter_text:
            return False
        field = self._cover_letter_locator()
        if field is None:
            return False
        try:
            current = field.input_value()
        except Exception:
            try:
                current = field.text_content() or ""
            except Exception:
                current = ""
        normalized_current = re.sub(r"[^a-z0-9]+", " ", current.lower()).strip()
        normalized_target = re.sub(r"[^a-z0-9]+", " ", cover_letter_text.lower()).strip()
        prefix = " ".join(normalized_target.split()[:12])
        verified = bool(prefix) and prefix in normalized_current
        if self.run_logger:
            self.run_logger.info(
                "Cover letter verification: verified=%s current_preview=%r target_preview=%r",
                verified,
                current[:160],
                cover_letter_text[:160],
            )
        return verified

    def _extract_validation_errors(self) -> str:
        texts = []
        for selector in ["[role='alert']", "[aria-live='assertive']", "[data-testid*='error']", ".validation-error", ".error"]:
            locator = self.page.locator(selector)
            for index in range(locator.count()):
                try:
                    text = (locator.nth(index).inner_text(timeout=500) or "").strip()
                except Exception:
                    text = ""
                if text and text not in texts:
                    texts.append(text)
        return " | ".join(texts)

    def _wait_for_navigation(self, before: tuple[str, str, str], *, intro_must_clear: bool = False, timeout_ms: int = 5000) -> tuple[bool, str]:
        elapsed = 0
        step = 250
        while elapsed < timeout_ms:
            if intro_must_clear and not self._is_intro_page():
                return True, ""
            after = self._page_signature()
            if after != before:
                return True, ""
            if self._is_final_review_page():
                return True, ""
            errors = self._extract_validation_errors()
            if errors:
                return False, errors
            self.page.wait_for_timeout(step)
            elapsed += step
        errors = self._extract_validation_errors()
        if errors:
            return False, errors
        return False, "navigation_timeout"

    def _submit_completion_detected(self) -> bool:
        return self._submit_success_url()

    def _advance_continue(self, *, intro_must_clear: bool = False) -> tuple[bool, str]:
        before = self._page_signature()
        if not self._click_button("continue"):
            return False, "continue_button_not_found"
        return self._wait_for_navigation(before, intro_must_clear=intro_must_clear)

    def _advance_submit(self) -> tuple[bool, str]:
        accepted = self._accept_review_consents()
        if self.run_logger and accepted:
            self.run_logger.info("Review consent count accepted: %d", accepted)
        before_url = self.page.url
        if not self._click_button("submit"):
            return False, "submit_button_not_found"
        try:
            self.page.wait_for_url(re.compile(r".*/apply/success(?:[/?#].*)?$", re.I), timeout=12000)
            if self.run_logger:
                self.run_logger.info("Submit completion detected: url=%s", self.page.url)
            return True, ""
        except PlaywrightTimeoutError:
            pass
        elapsed = 0
        step = 250
        timeout_ms = 12000
        while elapsed < timeout_ms:
            if self._submit_completion_detected():
                if self.run_logger:
                    self.run_logger.info("Submit completion detected: url=%s", self.page.url)
                return True, ""
            errors = self._extract_validation_errors()
            if errors:
                return False, errors
            if self.page.url != before_url and not is_seek_domain_url(self.page.url):
                return False, "submit_redirected_off_seek"
            self.page.wait_for_timeout(step)
            elapsed += step
        if self._submit_completion_detected():
            if self.run_logger:
                self.run_logger.info("Submit completion detected after wait: url=%s", self.page.url)
            return True, ""
        errors = self._extract_validation_errors()
        if errors:
            return False, errors
        return False, "submit_not_confirmed"

    def apply(self, job: JobDetails, choice: ResumeChoice, *, dry_run: bool = False) -> tuple[bool, str]:
        if dry_run:
            return True, "dry_run"
        apply_url = f"{job.url.rstrip('/')}/apply"
        self.page.goto(apply_url, wait_until="domcontentloaded")
        if not is_seek_domain_url(self.page.url):
            return False, "external_redirect"
        if self.already_applied_notice():
            return False, "already_applied"

        cover_letter_text = generate_cover_letter(choice.resume_text, f"{job.title}\n{job.description}", self.config)
        if self.run_logger:
            if cover_letter_text:
                self.run_logger.info("Cover letter generated: chars=%d preview=%r", len(cover_letter_text), cover_letter_text[:250])
            else:
                self.run_logger.info("Cover letter generated: none")

        if self._is_intro_page():
            if self._intro_resume_present():
                ok, reason = self._ensure_resume(choice.resume_path)
                if self.run_logger:
                    self.run_logger.info("Document handling: target_resume=%s success=%s action=%s", choice.resume_path, ok, reason)
                if not ok:
                    return False, reason
            if self._intro_cover_letter_present():
                ok, reason = self._ensure_cover_letter(cover_letter_text)
                if self.run_logger:
                    self.run_logger.info(
                        "Cover letter handling: generated=%s filled=%s chars=%d",
                        bool(cover_letter_text),
                        ok,
                        len(cover_letter_text or ""),
                    )
                if not ok:
                    return False, reason

            if self._intro_resume_present() and not self._verify_resume(choice.resume_path):
                return False, "intro_resume_verification_failed"
            if self._intro_cover_letter_present() and not self._verify_cover_letter(cover_letter_text):
                return False, "intro_cover_letter_verification_failed"

            advanced, detail = self._advance_continue(intro_must_clear=True)
            if not advanced:
                if self.run_logger and detail:
                    self.run_logger.info("Validation errors: %s", detail)
                return False, "validation_errors" if "Before you can continue" in detail else detail

        for attempt in range(1, 10):
            if self._submit_completion_detected():
                return True, "submitted"

            if self._is_intro_page():
                if self.run_logger:
                    self.run_logger.info("Unexpected return to intro page on attempt=%d", attempt)
                return False, "returned_to_intro_page"

            if self._is_final_review_page():
                if self.run_logger:
                    self.run_logger.info("Final review page detected on attempt=%d", attempt)
                advanced, detail = self._advance_submit()
                if advanced:
                    return True, "submitted"
                if not advanced:
                    if self.run_logger and detail:
                        self.run_logger.info("Validation errors: %s", detail)
                    return False, "validation_errors" if "Before you can continue" in detail else detail
                continue

            fill_questionnaire(
                self.page,
                self.config,
                choice.resume_text,
                f"{job.title}\n{job.description}",
                self.run_logger,
                question_store=self.question_store,
            )

            if self._is_final_review_page():
                if self.run_logger:
                    self.run_logger.info("Final review page detected after questionnaire on attempt=%d", attempt)
                advanced, detail = self._advance_submit()
                if advanced:
                    return True, "submitted"
                if not advanced:
                    if self.run_logger and detail:
                        self.run_logger.info("Validation errors: %s", detail)
                    return False, "validation_errors" if "Before you can continue" in detail else detail
                continue

            if self._continue_present():
                advanced, detail = self._advance_continue()
                if not advanced:
                    if self.run_logger and detail:
                        self.run_logger.info("Validation errors: %s", detail)
                    return False, "validation_errors" if "Before you can continue" in detail else detail
                continue

            if self._submit_present():
                advanced, detail = self._advance_submit()
                if advanced:
                    return True, "submitted"
                if not advanced:
                    if self.run_logger and detail:
                        self.run_logger.info("Validation errors: %s", detail)
                    return False, "validation_errors" if "Before you can continue" in detail else detail
                continue

            if self._submit_completion_detected():
                return True, "submitted"
        return False, "apply_flow_failed"
