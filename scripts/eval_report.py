import argparse
import os
import sys
from typing import Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from seekbot.settings import load_settings
from seekbot.storage import create_storage


def _print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def _print_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    if not rows:
        print("(none)")
        return
    string_rows = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in string_rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    print(" | ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in string_rows:
        print(" | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))


def _query_rows(conn, sql: str, params: Sequence[object] = ()) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        results = cur.fetchall()
    rows: list[tuple] = []
    for row in results:
        if isinstance(row, dict):
            rows.append(tuple(row.values()))
        else:
            rows.append(tuple(row))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a small DB-backed SeekBot eval report.")
    parser.add_argument("--top", type=int, default=10, help="Number of rows to show in each ranked section.")
    args = parser.parse_args()

    settings = load_settings()
    job_store, question_store = create_storage(settings)
    db = getattr(job_store, "db", None) or getattr(question_store, "db", None)
    if db is None:
        raise SystemExit("eval_report requires the Postgres storage backend.")

    conn = db.conn

    _print_section("Job Status Summary")
    _print_table(
        ["status", "count"],
        _query_rows(
            conn,
            """
            SELECT status, COUNT(*) AS count
            FROM jobs
            GROUP BY status
            ORDER BY count DESC, status ASC
            """,
        ),
    )

    _print_section("Failed Application Reasons")
    _print_table(
        ["reason", "count"],
        _query_rows(
            conn,
            """
            SELECT reason, COUNT(*) AS count
            FROM jobs
            WHERE status = 'failed_apply'
            GROUP BY reason
            ORDER BY count DESC, reason ASC
            LIMIT %s
            """,
            (args.top,),
        ),
    )

    _print_section("Role Outcome Summary")
    _print_table(
        ["role_key", "total", "applied", "apply_rate_pct"],
        _query_rows(
            conn,
            """
            SELECT
                COALESCE(NULLIF(role_key, ''), '(none)') AS role_key,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'applied') AS applied,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE status = 'applied') / NULLIF(COUNT(*), 0),
                    1
                ) AS apply_rate_pct
            FROM jobs
            GROUP BY COALESCE(NULLIF(role_key, ''), '(none)')
            ORDER BY total DESC, role_key ASC
            LIMIT %s
            """,
            (args.top,),
        ),
    )

    _print_section("QA Memory Summary")
    _print_table(
        ["verified", "count"],
        _query_rows(
            conn,
            """
            SELECT CASE WHEN verified THEN 'true' ELSE 'false' END AS verified, COUNT(*) AS count
            FROM qa_memory
            GROUP BY verified
            ORDER BY verified DESC
            """,
        ),
    )

    _print_section("Most Reused QA Memory")
    _print_table(
        ["times_used", "verified", "answered_by", "question_text", "answer"],
        _query_rows(
            conn,
            """
            SELECT
                times_used,
                CASE WHEN verified THEN 'true' ELSE 'false' END AS verified,
                answered_by,
                question_text,
                answer
            FROM qa_memory
            ORDER BY times_used DESC, last_seen DESC
            LIMIT %s
            """,
            (args.top,),
        ),
    )

    _print_section("Current Unverified QA Rows")
    _print_table(
        ["confidence", "answered_by", "times_used", "question_text", "answer"],
        _query_rows(
            conn,
            """
            SELECT
                COALESCE(ROUND(confidence::numeric, 2)::text, '') AS confidence,
                answered_by,
                times_used,
                question_text,
                answer
            FROM qa_memory
            WHERE verified = FALSE
            ORDER BY last_seen DESC
            LIMIT %s
            """,
            (args.top,),
        ),
    )

    _print_section("Question Wording Variants")
    _print_table(
        ["variants", "example_question"],
        _query_rows(
            conn,
            """
            SELECT COUNT(*) AS variants, MIN(question_text) AS example_question
            FROM qa_memory
            GROUP BY question_hash
            HAVING COUNT(*) > 1
            ORDER BY variants DESC, example_question ASC
            LIMIT %s
            """,
            (args.top,),
        ),
    )


if __name__ == "__main__":
    main()
