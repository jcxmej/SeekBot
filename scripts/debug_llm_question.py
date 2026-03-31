import argparse
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from playwright.sync_api import sync_playwright

from seekbot.llm import build_question_prompt, generate_with_current_provider, parse_question_response
from seekbot.resume_parser import extract_resume_text
from seekbot.seek.forms import build_qa_memory_table
from seekbot.seek.search import fetch_job_details, normalize_job_url
from seekbot.settings import load_settings
from seekbot.storage import QuestionMemoryStore


def _job_url_from_input(url: str) -> str:
    normalized = normalize_job_url(url)
    match = re.search(r"(https?://[^/]+/job/\d+)", normalized)
    return match.group(1) if match else normalized


def _job_id_from_url(url: str) -> str:
    match = re.search(r"/job/(\d+)", url or "")
    return match.group(1) if match else "unknown"


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return cleaned or "question"


def _resolve_resume(args, settings) -> tuple[str, str]:
    if args.resume_path:
        return args.resume_path, extract_resume_text(args.resume_path)
    if not args.resume_role:
        raise SystemExit("Provide either --resume-role or --resume-path.")
    resume_path = settings.defaults.role_resumes.get(args.resume_role)
    if not resume_path:
        raise SystemExit(f"Unknown resume role: {args.resume_role}")
    return resume_path, extract_resume_text(resume_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug the exact LLM prompt for one employer question.")
    parser.add_argument("job_url", help="Seek job URL or apply URL")
    parser.add_argument("--question", required=True, help="Question text to test")
    parser.add_argument("--option", action="append", default=[], help="Option text. Repeat for multiple options.")
    parser.add_argument("--multi-select", action="store_true", help="Use the multi-select option-question prompt")
    parser.add_argument("--resume-role", help="Configured resume role key, e.g. 'data engineer'")
    parser.add_argument("--resume-path", help="Absolute resume path override")
    parser.add_argument("--output-dir", default="debug_runs", help="Directory for saved prompt/response artifacts")
    parser.add_argument("--headless", action="store_true", help="Run Playwright headless while fetching the JD")
    parser.add_argument("--provider", help="Optional temporary provider override")
    parser.add_argument("--model", help="Optional temporary model override")
    args = parser.parse_args()

    settings = load_settings()
    config = settings.raw
    if args.provider:
        config.setdefault("llm", {})["provider"] = args.provider
    if args.model:
        config.setdefault("llm", {})["model"] = args.model

    resume_path, resume_text = _resolve_resume(args, settings)
    target_job_url = _job_url_from_input(args.job_url)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=args.headless, channel="chrome")
        page = browser.new_page()
        details = fetch_job_details(page, target_job_url)
        browser.close()

    question_store = QuestionMemoryStore(settings.logging.question_memory_csv_path)
    options = args.option or None
    qa_memory_table = build_qa_memory_table(config, question_store, args.question, options)
    prompt = build_question_prompt(
        resume_text,
        f"{details.title}\n{details.description}",
        args.question,
        config,
        options,
        qa_memory_table=qa_memory_table,
        allow_multiple=args.multi_select,
    )
    raw_response = generate_with_current_provider(prompt, config)
    parsed_response = parse_question_response(raw_response, options, allow_multiple=args.multi_select)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(
        args.output_dir,
        f"{timestamp}_{_job_id_from_url(target_job_url)}_{_slugify(args.question)[:50]}",
    )
    os.makedirs(run_dir, exist_ok=True)

    context = {
        "job_url": target_job_url,
        "job_title": details.title,
        "resume_role": args.resume_role or "",
        "resume_path": resume_path,
        "provider": config.get("llm", {}).get("provider", ""),
        "model": config.get("llm", {}).get("model", ""),
        "question": args.question,
        "options": options or [],
        "multi_select": bool(args.multi_select),
    }

    with open(os.path.join(run_dir, "context.json"), "w") as handle:
        json.dump(context, handle, indent=2)
    with open(os.path.join(run_dir, "qa_memory_table.txt"), "w") as handle:
        handle.write(qa_memory_table)
    with open(os.path.join(run_dir, "prompt.txt"), "w") as handle:
        handle.write(prompt)
    with open(os.path.join(run_dir, "response_raw.txt"), "w") as handle:
        handle.write(raw_response)
    with open(os.path.join(run_dir, "response_parsed.json"), "w") as handle:
        json.dump(parsed_response, handle, indent=2)
    with open(os.path.join(run_dir, "job_description.txt"), "w") as handle:
        handle.write(f"{details.title}\n\n{details.description}")

    print(f"Saved debug artifacts to: {run_dir}")
    print(json.dumps(parsed_response, indent=2))


if __name__ == "__main__":
    main()
