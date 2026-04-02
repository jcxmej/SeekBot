from __future__ import annotations
import logging
import os
from pathlib import Path
from difflib import SequenceMatcher

from seekbot.domain import ApplicationRecord
from seekbot.matching import semantic_embedding
from seekbot.storage.jobs import (
    RETRYABLE_FAILURE_STATUSES,
    TERMINAL_SKIP_STATUSES,
    CsvJobStore,
    resolve_job_key,
    resolve_job_lookup_key,
)
from seekbot.storage.question_memory import (
    QuestionMemoryStore,
    normalize_options,
    normalize_question,
    options_key,
    question_embedding_text,
    question_hash,
    question_lookup_key,
)


def _vector_literal(embedding: tuple[float, ...] | list[float] | None) -> str | None:
    values = list(embedding or [])
    if not values:
        return None
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() == "none":
        return None
    try:
        return float(text)
    except Exception:
        return None


def _question_embedding(question_text: str, options: list[str] | None, config: dict) -> tuple[float, ...]:
    return semantic_embedding(question_embedding_text(question_text, options), config)


class PostgresDB:
    def __init__(
        self,
        dsn: str,
        *,
        vector_dims: int,
        config: dict,
        jobs_csv_path: str,
        qa_csv_path: str,
        bootstrap_from_csv: bool,
    ):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except Exception as exc:
            raise RuntimeError(f"psycopg is not available: {exc}") from exc

        self._psycopg = psycopg
        self.conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self.config = config
        self._ensure_schema(vector_dims)
        if bootstrap_from_csv:
            self._bootstrap_from_csv(jobs_csv_path=jobs_csv_path, qa_csv_path=qa_csv_path)

    def _ensure_schema(self, vector_dims: int) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        schema_sql = schema_path.read_text().replace("__VECTOR_DIMS__", str(int(vector_dims)))
        with self.conn.cursor() as cur:
            cur.execute(schema_sql)

    def _bootstrap_from_csv(self, *, jobs_csv_path: str, qa_csv_path: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM jobs")
            jobs_count = int(cur.fetchone()["count"])
            cur.execute("SELECT COUNT(*) AS count FROM qa_memory")
            qa_count = int(cur.fetchone()["count"])
        if jobs_count == 0 and os.path.exists(jobs_csv_path):
            csv_jobs = CsvJobStore(jobs_csv_path)
            job_store = PostgresJobStore(self)
            for row in csv_jobs.rows.values():
                job_store.upsert_row(row)
        if qa_count == 0 and os.path.exists(qa_csv_path):
            csv_memory = QuestionMemoryStore(qa_csv_path)
            question_store = PostgresQuestionMemoryStore(self, self.config)
            for row in csv_memory.rows:
                question_store.upsert_row(row)


class PostgresJobStore:
    def __init__(self, db: PostgresDB):
        self.db = db

    def upsert_row(self, row: dict) -> None:
        job_key = resolve_job_key(_clean_text(row.get("url", "")), _clean_text(row.get("job_index", "")))
        if not job_key:
            return
        payload = {
            "job_key": job_key,
            "job_id": _clean_text(row.get("job_index", "")) or job_key,
            "status": _clean_text(row.get("status", "")),
            "reason": _clean_text(row.get("reason", "")),
            "url": _clean_text(row.get("url", "")),
            "title": _clean_text(row.get("title", "")),
            "company": _clean_text(row.get("company", "")),
            "location": _clean_text(row.get("location", "")),
            "hr_name": _clean_text(row.get("hr_name", "")),
            "hr_email": _clean_text(row.get("hr_email", "")),
            "hr_phone": _clean_text(row.get("hr_phone", "")),
            "external_url": _clean_text(row.get("external_url", "")),
            "search_url": _clean_text(row.get("search_url", "")),
            "keyword": _clean_text(row.get("keyword", "")),
            "role_key": _clean_text(row.get("role_key", "")),
            "selected_resume_role": _clean_text(row.get("selected_resume_role", "")),
            "resume_path": _clean_text(row.get("resume_path", "")),
            "quick_apply": _clean_text(row.get("quick_apply", "")).lower() in {"1", "true", "yes"},
            "compatibility_score": _optional_float(row.get("compatibility_score")),
            "compatibility_threshold": _optional_float(row.get("compatibility_threshold")),
            "matched_keywords": _clean_text(row.get("matched_keywords", "")),
            "missing_keywords": _clean_text(row.get("missing_keywords", "")),
            "dry_run": _clean_text(row.get("dry_run", "")).lower() in {"1", "true", "yes"},
            "external": _clean_text(row.get("external", "")).lower() in {"1", "true", "yes"},
            "timestamp": _clean_text(row.get("timestamp", "")) or None,
        }
        sql = """
        INSERT INTO jobs (
            job_key, job_id, timestamp, status, reason, url, title, company, location,
            hr_name, hr_email, hr_phone, external_url, search_url, keyword, role_key,
            selected_resume_role, resume_path, quick_apply, compatibility_score,
            compatibility_threshold, matched_keywords, missing_keywords, dry_run, external
        ) VALUES (
            %(job_key)s, %(job_id)s, COALESCE(%(timestamp)s::timestamptz, NOW()), %(status)s, %(reason)s, %(url)s,
            %(title)s, %(company)s, %(location)s, %(hr_name)s, %(hr_email)s, %(hr_phone)s,
            %(external_url)s, %(search_url)s, %(keyword)s, %(role_key)s, %(selected_resume_role)s,
            %(resume_path)s, %(quick_apply)s, %(compatibility_score)s, %(compatibility_threshold)s,
            %(matched_keywords)s, %(missing_keywords)s, %(dry_run)s, %(external)s
        )
        ON CONFLICT (job_key) DO UPDATE SET
            job_id = EXCLUDED.job_id,
            timestamp = EXCLUDED.timestamp,
            status = EXCLUDED.status,
            reason = EXCLUDED.reason,
            url = EXCLUDED.url,
            title = EXCLUDED.title,
            company = EXCLUDED.company,
            location = EXCLUDED.location,
            hr_name = EXCLUDED.hr_name,
            hr_email = EXCLUDED.hr_email,
            hr_phone = EXCLUDED.hr_phone,
            external_url = EXCLUDED.external_url,
            search_url = EXCLUDED.search_url,
            keyword = EXCLUDED.keyword,
            role_key = EXCLUDED.role_key,
            selected_resume_role = EXCLUDED.selected_resume_role,
            resume_path = EXCLUDED.resume_path,
            quick_apply = EXCLUDED.quick_apply,
            compatibility_score = EXCLUDED.compatibility_score,
            compatibility_threshold = EXCLUDED.compatibility_threshold,
            matched_keywords = EXCLUDED.matched_keywords,
            missing_keywords = EXCLUDED.missing_keywords,
            dry_run = EXCLUDED.dry_run,
            external = EXCLUDED.external
        """
        with self.db.conn.cursor() as cur:
            cur.execute(sql, payload)

    def append(self, record: ApplicationRecord) -> None:
        self.upsert_row(
            {
                "status": record.status,
                "reason": record.reason,
                "url": record.url,
                "title": record.title,
                "company": record.company,
                "location": record.location,
                "hr_name": record.contact.name,
                "hr_email": record.contact.email,
                "hr_phone": record.contact.phone,
                "external_url": record.external_url,
                "search_url": record.search_url,
                "keyword": record.keyword or "",
                "role_key": record.role_key,
                "selected_resume_role": record.selected_resume_role,
                "resume_path": record.resume_path,
                "quick_apply": record.quick_apply,
                "compatibility_score": record.compatibility.score if record.compatibility else None,
                "compatibility_threshold": record.compatibility_threshold,
                "matched_keywords": ", ".join(record.compatibility.matched_keywords if record.compatibility else []),
                "missing_keywords": ", ".join(record.compatibility.missing_keywords if record.compatibility else []),
                "dry_run": record.dry_run,
                "external": record.external,
                "job_index": record.job_index,
            }
        )

    def get(self, url_or_job_id: str) -> dict | None:
        key = resolve_job_lookup_key(url_or_job_id)
        if not key:
            return None
        with self.db.conn.cursor() as cur:
            cur.execute("SELECT * FROM jobs WHERE job_key = %s", (key,))
            return cur.fetchone()

    def should_skip(self, url_or_job_id: str) -> bool:
        row = self.get(url_or_job_id)
        return bool(row and row.get("status") in TERMINAL_SKIP_STATUSES)

    def status_summary(self) -> dict[str, int]:
        with self.db.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = ANY(%s)) AS terminal,
                    COUNT(*) FILTER (WHERE status = ANY(%s)) AS retryable_failed
                FROM jobs
                """,
                (list(TERMINAL_SKIP_STATUSES), list(RETRYABLE_FAILURE_STATUSES)),
            )
            row = cur.fetchone()
        return {
            "total": int(row["total"]),
            "terminal": int(row["terminal"]),
            "retryable_failed": int(row["retryable_failed"]),
        }


class PostgresQuestionMemoryStore:
    def __init__(self, db: PostgresDB, config: dict):
        self.db = db
        self.config = config

    def _exact_row(self, question_text: str, options: list[str] | None) -> dict | None:
        key = question_lookup_key(question_text, options)
        if not key:
            return None
        with self.db.conn.cursor() as cur:
            cur.execute("SELECT * FROM qa_memory WHERE memory_key = %s", (key,))
            return cur.fetchone()

    def _row_payload(
        self,
        *,
        question_text: str,
        options: list[str] | None,
        answer: str,
        answered_by: str,
        confidence: float | None,
        verified: bool,
        times_used: int,
    ) -> dict:
        normalized_options = normalize_options(options)
        embedding = _question_embedding(question_text, normalized_options, self.config)
        return {
            "memory_key": question_lookup_key(question_text, normalized_options),
            "question_hash": question_hash(question_text),
            "normalized_question": normalize_question(question_text),
            "question_text": (question_text or "").strip(),
            "has_options": bool(normalized_options),
            "options": " | ".join(normalized_options),
            "options_signature": options_key(normalized_options),
            "answer": (answer or "").strip(),
            "answered_by": str(answered_by or "").strip().lower(),
            "confidence": None if confidence is None else float(confidence),
            "times_used": max(int(times_used), 1),
            "verified": bool(verified),
            "embedding": _vector_literal(embedding),
        }

    def upsert_row(self, row: dict) -> None:
        options = row.get("options", "")
        option_list = options.split(" | ") if isinstance(options, str) and options else list(options or [])
        payload = self._row_payload(
            question_text=row.get("question_text", ""),
            options=option_list,
            answer=row.get("answer", ""),
            answered_by=row.get("answered_by", ""),
            confidence=_optional_float(row.get("confidence")),
            verified=_clean_text(row.get("verified", "")).lower() in {"1", "true", "yes"},
            times_used=int(_clean_text(row.get("times_used", "") or "1") or "1"),
        )
        sql = """
        INSERT INTO qa_memory (
            memory_key, question_hash, normalized_question, question_text, has_options, options,
            options_signature, answer, answered_by, confidence, times_used, last_seen, verified, embedding
        ) VALUES (
            %(memory_key)s, %(question_hash)s, %(normalized_question)s, %(question_text)s, %(has_options)s,
            %(options)s, %(options_signature)s, %(answer)s, %(answered_by)s, %(confidence)s, %(times_used)s,
            NOW(), %(verified)s, %(embedding)s::vector
        )
        ON CONFLICT (memory_key) DO UPDATE SET
            question_hash = EXCLUDED.question_hash,
            normalized_question = EXCLUDED.normalized_question,
            question_text = EXCLUDED.question_text,
            has_options = EXCLUDED.has_options,
            options = EXCLUDED.options,
            options_signature = EXCLUDED.options_signature,
            answer = EXCLUDED.answer,
            answered_by = EXCLUDED.answered_by,
            confidence = EXCLUDED.confidence,
            times_used = EXCLUDED.times_used,
            last_seen = NOW(),
            verified = EXCLUDED.verified,
            embedding = EXCLUDED.embedding
        """
        with self.db.conn.cursor() as cur:
            cur.execute(sql, payload)

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
        existing = self._exact_row(question_text, options)
        if not existing:
            self.upsert_row(
                {
                    "question_text": question_text,
                    "options": " | ".join(normalize_options(options)),
                    "answer": answer,
                    "answered_by": answered_by,
                    "confidence": confidence,
                    "verified": verified,
                    "times_used": 1,
                }
            )
            return

        previous_answer = existing.get("answer", "")
        previous_uses = int(existing.get("times_used") or 1)
        if previous_answer == answer:
            updated_source = answered_by if answered_by == "user" else (existing.get("answered_by", answered_by) or answered_by)
            updated_confidence = confidence
            if updated_source != "user" and existing.get("confidence") is not None:
                try:
                    updated_confidence = max(float(existing.get("confidence") or 0.0), float(confidence or 0.0))
                except Exception:
                    updated_confidence = confidence
            updated_verified = bool(existing.get("verified")) or verified
        else:
            updated_source = answered_by
            updated_confidence = confidence
            updated_verified = verified or bool(existing.get("verified"))

        self.upsert_row(
            {
                "question_text": question_text,
                "options": " | ".join(normalize_options(options)),
                "answer": answer,
                "answered_by": updated_source,
                "confidence": updated_confidence,
                "verified": updated_verified,
                "times_used": previous_uses + 1,
            }
        )

    def lookup_exact(self, question_text: str, options: list[str] | None) -> dict | None:
        return self._exact_row(question_text, options)

    def reusable(self, row: dict | None) -> bool:
        return bool(row and row.get("verified"))

    def lookup_similar_verified(
        self,
        question_text: str,
        options: list[str] | None,
        *,
        min_similarity: float = 0.68,
    ) -> dict | None:
        target_key = question_lookup_key(question_text, options)
        target_options = options_key(options)
        target_question = normalize_question(question_text)
        embedding = _vector_literal(_question_embedding(question_text, options, self.config))
        with self.db.conn.cursor() as cur:
            if embedding:
                cur.execute(
                    """
                    SELECT
                        question_text,
                        options,
                        answer,
                        answered_by,
                        confidence,
                        verified,
                        1 - (embedding <=> %s::vector) AS similarity
                    FROM qa_memory
                    WHERE memory_key <> %s
                      AND verified = TRUE
                    ORDER BY
                        CASE WHEN options_signature = %s AND %s <> '' THEN 1 ELSE 0 END DESC,
                        similarity DESC NULLS LAST,
                        last_seen DESC
                    LIMIT 1
                    """,
                    (embedding, target_key, target_options, target_options),
                )
                row = cur.fetchone()
                if row and row.get("similarity") is not None and float(row.get("similarity") or 0.0) >= min_similarity:
                    return row

            cur.execute(
                """
                SELECT question_text, options, answer, answered_by, confidence, verified
                FROM qa_memory
                WHERE memory_key <> %s
                  AND verified = TRUE
                ORDER BY
                    CASE WHEN options_signature = %s AND %s <> '' THEN 1 ELSE 0 END DESC,
                    last_seen DESC
                LIMIT 50
                """,
                (target_key, target_options, target_options),
            )
            rows = cur.fetchall()

        best_row: dict | None = None
        best_score = 0.0
        for row in rows:
            similarity = SequenceMatcher(None, target_question, normalize_question(row.get("question_text", ""))).ratio()
            if target_options and options_key((row.get("options", "") or "").split(" | ")) == target_options:
                similarity += 0.1
            if similarity > best_score:
                best_score = similarity
                best_row = row
        if not best_row or best_score < min_similarity:
            return None
        best_row = dict(best_row)
        best_row["similarity"] = round(best_score, 4)
        return best_row

    def format_prompt_context(self, question_text: str, options: list[str] | None, limit: int = 5) -> str:
        embedding = _vector_literal(_question_embedding(question_text, options, self.config))
        target_options = options_key(options)
        target_key = question_lookup_key(question_text, options)
        min_similarity = 0.55
        with self.db.conn.cursor() as cur:
            if embedding:
                cur.execute(
                    """
                    SELECT
                        question_text,
                        options,
                        answer,
                        answered_by,
                        confidence,
                        verified,
                        1 - (embedding <=> %s::vector) AS similarity
                    FROM qa_memory
                    WHERE memory_key <> %s
                      AND verified = TRUE
                      AND 1 - (embedding <=> %s::vector) >= %s
                    ORDER BY
                        CASE WHEN options_signature = %s AND %s <> '' THEN 1 ELSE 0 END DESC,
                        similarity DESC NULLS LAST,
                        verified DESC,
                        last_seen DESC
                    LIMIT %s
                    """,
                    (embedding, target_key, embedding, min_similarity, target_options, target_options, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        question_text,
                        options,
                        answer,
                        answered_by,
                        confidence,
                        verified,
                        0.0 AS similarity
                    FROM qa_memory
                    WHERE memory_key <> %s
                      AND verified = TRUE
                    ORDER BY
                        CASE WHEN options_signature = %s AND %s <> '' THEN 1 ELSE 0 END DESC,
                        verified DESC,
                        last_seen DESC
                    LIMIT %s
                    """,
                    (target_key, target_options, target_options, max(limit * 5, 20)),
                )
            rows = cur.fetchall()
        if not embedding:
            filtered_rows: list[dict] = []
            target_question = normalize_question(question_text)
            for row in rows:
                similarity = SequenceMatcher(None, target_question, normalize_question(row.get("question_text", ""))).ratio()
                if target_options and options_key((row.get("options", "") or "").split(" | ")) == target_options:
                    similarity += 0.2
                if similarity >= min_similarity:
                    filtered = dict(row)
                    filtered["similarity"] = round(similarity, 4)
                    filtered_rows.append(filtered)
            rows = filtered_rows[:limit]
        if not rows:
            return "N/A"
        lines = ["question_text | options | answer | answered_by | confidence | verified"]
        for row in rows:
            lines.append(
                f"{str(row.get('question_text', ''))[:220]} | {str(row.get('options', ''))[:220]} | "
                f"{str(row.get('answer', ''))[:160]} | {str(row.get('answered_by', ''))} | "
                f"{'' if row.get('confidence') is None else row.get('confidence')} | {str(row.get('verified', False)).lower()}"
            )
        return "\n".join(lines)

    def summary(self) -> dict[str, int]:
        with self.db.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE verified) AS verified FROM qa_memory")
            row = cur.fetchone()
        return {"total": int(row["total"]), "verified": int(row["verified"])}

    def prune_unverified(self) -> int:
        with self.db.conn.cursor() as cur:
            cur.execute("DELETE FROM qa_memory WHERE verified = FALSE")
            return int(cur.rowcount or 0)

def create_storage(settings):
    if settings.storage.backend != "postgres":
        return CsvJobStore(settings.logging.csv_log_path), QuestionMemoryStore(settings.logging.question_memory_csv_path)

    dsn = settings.storage.dsn or os.environ.get(settings.storage.dsn_env, "").strip()
    if not dsn:
        message = "Postgres storage selected but no DSN was provided."
        if not settings.storage.fallback_to_csv:
            raise RuntimeError(message)
        logging.warning("%s Falling back to CSV storage.", message)
        return CsvJobStore(settings.logging.csv_log_path), QuestionMemoryStore(settings.logging.question_memory_csv_path)

    try:
        db = PostgresDB(
            dsn,
            vector_dims=settings.storage.vector_dims,
            config=settings.raw,
            jobs_csv_path=settings.logging.csv_log_path,
            qa_csv_path=settings.logging.question_memory_csv_path,
            bootstrap_from_csv=settings.storage.bootstrap_from_csv,
        )
        logging.info("Using Postgres storage backend.")
        return PostgresJobStore(db), PostgresQuestionMemoryStore(db, settings.raw)
    except Exception as exc:
        if not settings.storage.fallback_to_csv:
            raise
        logging.warning("Postgres storage unavailable; falling back to CSV storage: %s", exc)
        return CsvJobStore(settings.logging.csv_log_path), QuestionMemoryStore(settings.logging.question_memory_csv_path)
