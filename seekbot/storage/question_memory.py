import csv
import hashlib
import os
import re
import time
from difflib import SequenceMatcher


CSV_FIELDS = [
    "question_hash",
    "question_text",
    "has_options",
    "options",
    "answer",
    "answered_by",
    "confidence",
    "times_used",
    "last_seen",
    "verified",
]


def normalize_question(text: str | None) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_options(options: list[str] | None) -> list[str]:
    return [re.sub(r"\s+", " ", (option or "").strip()) for option in (options or []) if (option or "").strip()]


def options_key(options: list[str] | None) -> str:
    return " | ".join(sorted(normalize_options(options)))


def question_hash(question_text: str) -> str:
    normalized = normalize_question(question_text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12] if normalized else ""


def question_lookup_key(question_text: str, options: list[str] | None) -> str:
    normalized = normalize_question(question_text)
    option_text = options_key(options)
    if not normalized and not option_text:
        return ""
    return hashlib.sha1(f"{normalized}\n{option_text}".encode("utf-8")).hexdigest()


def question_embedding_text(question_text: str, options: list[str] | None) -> str:
    normalized_question = (question_text or "").strip()
    normalized_options = normalize_options(options)
    if not normalized_options:
        return normalized_question
    return f"{normalized_question}\nOPTIONS:\n- " + "\n- ".join(normalized_options)


class QuestionMemoryStore:
    def __init__(self, path: str):
        self.path = path
        self.rows: list[dict] = []
        self._load_existing()

    def _normalize_row(self, row: dict) -> dict:
        normalized = {field: str(row.get(field, "") or "") for field in CSV_FIELDS}
        normalized["answered_by"] = normalized["answered_by"].strip().lower()
        normalized["has_options"] = "true" if normalized["has_options"].lower() in {"1", "true", "yes"} else "false"
        normalized["times_used"] = normalized["times_used"] or "1"
        normalized["verified"] = "true" if normalized["verified"].lower() in {"1", "true", "yes"} else "false"
        return normalized

    def _load_existing(self) -> None:
        if not os.path.exists(self.path):
            return
        changed = False
        with open(self.path, newline="") as handle:
            reader = csv.DictReader(handle)
            for raw_row in reader:
                normalized = self._normalize_row(raw_row)
                if any(str(raw_row.get(field, "") or "") != normalized.get(field, "") for field in CSV_FIELDS):
                    changed = True
                self.rows.append(normalized)
        if changed:
            self._write_all()

    def _write_all(self) -> None:
        with open(self.path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for row in self.rows:
                writer.writerow(self._normalize_row(row))

    def _make_row(
        self,
        *,
        question_text: str,
        options: list[str] | None,
        answer: str,
        answered_by: str,
        confidence: float | None,
        verified: bool,
        times_used: int = 1,
    ) -> dict:
        normalized_options = normalize_options(options)
        return {
            "question_hash": question_hash(question_text),
            "question_text": (question_text or "").strip(),
            "has_options": "true" if normalized_options else "false",
            "options": " | ".join(normalized_options),
            "answer": (answer or "").strip(),
            "answered_by": answered_by,
            "confidence": "" if confidence is None else f"{float(confidence):.2f}",
            "times_used": str(max(times_used, 1)),
            "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
            "verified": "true" if verified else "false",
        }

    def _exact_index(self, question_text: str, options: list[str] | None) -> int | None:
        target_key = question_lookup_key(question_text, options)
        for index, row in enumerate(self.rows):
            row_options = row.get("options", "").split(" | ") if row.get("options") else []
            if question_lookup_key(row.get("question_text", ""), row_options) == target_key:
                return index
        return None

    def remember(
        self,
        *,
        question_text: str,
        options: list[str] | None,
        answer: str,
        answered_by: str,
        confidence: float | None,
        verified: bool,
    ) -> None:
        if not question_text or not answer:
            return
        index = self._exact_index(question_text, options)
        if index is None:
            self.rows.append(
                self._make_row(
                    question_text=question_text,
                    options=options,
                    answer=answer,
                    answered_by=answered_by,
                    confidence=confidence,
                    verified=verified,
                    times_used=1,
                )
            )
            self._write_all()
            return

        row = self.rows[index]
        previous_answer = row.get("answer", "")
        previous_uses = int(row.get("times_used") or 1)
        if previous_answer == answer:
            updated_source = answered_by if answered_by == "user" else (row.get("answered_by", answered_by) or answered_by)
            updated_confidence = confidence
            if updated_source != "user" and row.get("confidence"):
                try:
                    updated_confidence = max(float(row.get("confidence") or 0.0), float(confidence or 0.0))
                except Exception:
                    updated_confidence = confidence
            updated = self._make_row(
                question_text=question_text,
                options=options,
                answer=answer,
                answered_by=updated_source,
                confidence=updated_confidence,
                verified=row.get("verified", "false") == "true" or verified,
                times_used=previous_uses + 1,
            )
        else:
            updated = self._make_row(
                question_text=question_text,
                options=options,
                answer=answer,
                answered_by=answered_by,
                confidence=confidence,
                verified=verified or row.get("verified", "false") == "true",
                times_used=previous_uses + 1,
            )
        self.rows[index] = updated
        self._write_all()

    def lookup_exact(self, question_text: str, options: list[str] | None) -> dict | None:
        index = self._exact_index(question_text, options)
        if index is None:
            return None
        return self.rows[index]

    def reusable(self, row: dict | None) -> bool:
        if not row:
            return False
        return row.get("verified", "false") == "true"

    def lookup_similar_verified(
        self,
        question_text: str,
        options: list[str] | None,
        *,
        min_similarity: float = 0.68,
    ) -> dict | None:
        target_question = normalize_question(question_text)
        target_options = options_key(options)
        target_key = question_lookup_key(question_text, options)
        best_row: dict | None = None
        best_score = 0.0
        for row in self.rows:
            if row.get("verified", "false") != "true":
                continue
            row_options = row.get("options", "").split(" | ") if row.get("options") else []
            if question_lookup_key(row.get("question_text", ""), row_options) == target_key:
                continue
            row_question = normalize_question(row.get("question_text", ""))
            similarity = SequenceMatcher(None, target_question, row_question).ratio()
            if target_options and options_key(row_options) == target_options:
                similarity += 0.1
            if similarity > best_score:
                best_score = similarity
                best_row = row
        if not best_row or best_score < min_similarity:
            return None
        result = dict(best_row)
        result["similarity"] = round(best_score, 4)
        return result

    def format_prompt_context(self, question_text: str, options: list[str] | None, limit: int = 5) -> str:
        target_question = normalize_question(question_text)
        target_options = options_key(options)
        scored: list[tuple[float, dict]] = []
        for row in self.rows:
            if row.get("verified", "false") != "true":
                continue
            row_question = normalize_question(row.get("question_text", ""))
            # This fuzzy comparison is prompt-context only. It does not auto-reuse answers.
            similarity = SequenceMatcher(None, target_question, row_question).ratio()
            if target_options and options_key(row.get("options", "").split(" | ") if row.get("options") else []) == target_options:
                similarity += 0.2
            if similarity >= 0.55:
                scored.append((similarity, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return "N/A"
        lines = ["question_text | options | answer | answered_by | confidence | verified"]
        for _, row in scored[:limit]:
            lines.append(
                f"{row.get('question_text', '')[:220]} | {row.get('options', '')[:220]} | "
                f"{row.get('answer', '')[:160]} | {row.get('answered_by', '')} | "
                f"{row.get('confidence', '')} | {row.get('verified', '')}"
            )
        return "\n".join(lines)

    def summary(self) -> dict[str, int]:
        verified = sum(1 for row in self.rows if row.get("verified") == "true")
        return {"total": len(self.rows), "verified": verified}

    def prune_unverified(self) -> int:
        before = len(self.rows)
        self.rows = [row for row in self.rows if row.get("verified") == "true"]
        removed = before - len(self.rows)
        if removed:
            self._write_all()
        return removed

    def record_application_event(
        self,
        *,
        kind: str,
        question_text: str,
        options: list[str] | None,
        resolution: dict | None,
        final_value: str | None,
        status: str,
    ) -> None:
        return None
