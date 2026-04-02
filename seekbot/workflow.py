import logging
import re
from dataclasses import replace

from seekbot.llm import extract_contact, set_logger
from seekbot.logging_utils import BotLoggers
from seekbot.matching import compute_compatibility, cosine_similarity, extract_taxonomy_keywords, semantic_embedding
from seekbot.domain import ApplicationRecord, CompatibilityResult, ContactInfo, ResumeChoice, ResumeProfile, SearchPlan
from seekbot.resume_parser import extract_resume_text
from seekbot.seek.application import ApplicationFlow
from seekbot.seek.browser import SeekBrowser
from seekbot.seek.search import build_search_urls, fetch_job_details, find_next_page_url, gather_job_cards
from seekbot.settings import Settings
from seekbot.storage import create_storage


def build_search_plans(settings: Settings, search_url: str | None = None, keywords: list[str] | None = None) -> list[SearchPlan]:
    if search_url:
        return [SearchPlan(role_key="manual_search", keyword=None, search_url=search_url)]
    role_keywords = keywords or list(settings.defaults.role_resumes.keys())
    urls = build_search_urls(role_keywords, settings.defaults.location)
    return [SearchPlan(role_key=keyword, keyword=keyword, search_url=url) for keyword, url in zip(role_keywords, urls)]


def load_resume_profiles(settings: Settings, resume_override: str | None = None) -> list[ResumeProfile]:
    if resume_override:
        text = extract_resume_text(resume_override)
        keywords = extract_taxonomy_keywords(text, settings.raw.get("matching", {}).get("taxonomy", []))
        embedding = semantic_embedding(text, settings.raw)
        return [
            ResumeProfile(
                role_key="override_resume",
                path=resume_override,
                text=text,
                keywords=keywords,
                embedding=embedding,
            )
        ]
    profiles = []
    seen_paths: dict[str, str] = {}
    seen_keywords: dict[str, list[str]] = {}
    seen_embeddings: dict[str, tuple[float, ...]] = {}
    for role_key, path in settings.defaults.role_resumes.items():
        if path in seen_paths:
            text = seen_paths[path]
            keywords = seen_keywords[path]
            embedding = seen_embeddings[path]
        else:
            text = extract_resume_text(path)
            keywords = extract_taxonomy_keywords(text, settings.raw.get("matching", {}).get("taxonomy", []))
            embedding = semantic_embedding(text, settings.raw)
            seen_paths[path] = text
            seen_keywords[path] = keywords
            seen_embeddings[path] = embedding
        profiles.append(ResumeProfile(role_key=role_key, path=path, text=text, keywords=keywords, embedding=embedding))
    return profiles


def _role_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", (text or "").lower()) if token}


def _title_role_overlap(job_title: str, role_key: str) -> float:
    title_tokens = _role_tokens(job_title)
    role_tokens = _role_tokens(role_key)
    if not title_tokens or not role_tokens:
        return 0.0
    normalized_title = re.sub(r"\s+", " ", (job_title or "").lower()).strip()
    normalized_role = re.sub(r"\s+", " ", (role_key or "").lower()).strip()
    if normalized_role and normalized_role in normalized_title:
        return 1.0
    overlap = title_tokens & role_tokens
    return len(overlap) / len(role_tokens)


def _title_role_match(job_title: str, role_key: str, config: dict) -> float:
    lexical = _title_role_overlap(job_title, role_key)
    title_embedding = semantic_embedding(job_title, config)
    role_embedding = semantic_embedding(role_key, config)
    semantic = max(0.0, cosine_similarity(title_embedding, role_embedding))
    if semantic and lexical:
        return round((semantic * 0.7) + (lexical * 0.3), 4)
    return round(semantic or lexical, 4)


def choose_best_resume(search_role: str, job_text: str, profiles: list[ResumeProfile], config: dict) -> ResumeChoice:
    best = None
    scores = []
    selection_scores = []
    anchor = None
    job_title = next((line.strip() for line in (job_text or "").splitlines() if line.strip()), "")
    taxonomy = list((config.get("matching", {}) or {}).get("taxonomy", []))
    resolved_job_keywords = extract_taxonomy_keywords(job_text, taxonomy)
    resolved_job_embedding = semantic_embedding(job_text, config)
    selection_cfg = (config.get("matching", {}) or {}).get("resume_selection", {})
    compatibility_weight = float(selection_cfg.get("compatibility_weight", 0.75))
    title_weight = float(selection_cfg.get("title_weight", 0.2))
    search_role_weight = float(selection_cfg.get("search_role_weight", 0.05))
    title_match_threshold = float(selection_cfg.get("title_match_threshold", 0.6))
    title_matches = {profile.role_key: _title_role_match(job_title, profile.role_key, config) for profile in profiles}
    title_signal_active = max(title_matches.values(), default=0.0) >= title_match_threshold
    for profile in profiles:
        title_match = title_matches.get(profile.role_key, 0.0)
        compatibility_dict = compute_compatibility(
            profile.text,
            job_text,
            config,
            resume_keywords=profile.keywords,
            resume_embedding=profile.embedding,
            job_keywords=resolved_job_keywords,
            job_embedding=resolved_job_embedding,
        )
        compatibility = CompatibilityResult(**compatibility_dict)
        scores.append((profile.role_key, compatibility.score))
        selection_score = (
            (compatibility.score / 10.0) * compatibility_weight
            + (title_match if title_signal_active else 0.0) * title_weight
            + (1.0 if profile.role_key == search_role else 0.0) * search_role_weight
        )
        selection_scores.append((profile.role_key, round(selection_score, 3)))
        rank = (
            round(selection_score, 6),
            compatibility.score,
            title_match,
            1 if profile.role_key == search_role else 0,
        )
        candidate = {
            "rank": rank,
            "profile": profile,
            "compatibility": compatibility,
            "title_match": title_match,
        }
        if profile.role_key == search_role:
            anchor = candidate
        if best is None or rank > best["rank"]:
            best = candidate
    assert best is not None
    switch_margin = float(config.get("defaults", {}).get("resume_switch_margin", 2.0))
    if anchor is not None and best["profile"].role_key != search_role and not title_signal_active:
        anchor_score = anchor["compatibility"].score
        best_score = best["compatibility"].score
        if best_score - anchor_score < switch_margin:
            best = anchor
    return ResumeChoice(
        search_role=search_role,
        selected_role=best["profile"].role_key,
        resume_path=best["profile"].path,
        resume_text=best["profile"].text,
        compatibility=best["compatibility"],
        candidate_scores=sorted(scores, key=lambda item: item[1], reverse=True),
        selection_scores=sorted(selection_scores, key=lambda item: item[1], reverse=True),
    )


def _merge_contact(original: ContactInfo, llm_contact: dict | None) -> ContactInfo:
    if not llm_contact:
        return original
    return ContactInfo(
        name=original.name or llm_contact.get("name", ""),
        email=original.email or llm_contact.get("email", ""),
        phone=original.phone or llm_contact.get("phone", ""),
    )


def _extract_seek_job_id(url: str) -> str:
    match = re.search(r"/job/(\d+)", url or "")
    return match.group(1) if match else ""


def _make_record(
    *,
    status: str,
    reason: str,
    details,
    plan: SearchPlan,
    choice: ResumeChoice | None,
    compatibility_threshold: float,
    dry_run: bool,
    external: bool,
    job_index: str,
) -> ApplicationRecord:
    compatibility = choice.compatibility if choice else None
    return ApplicationRecord(
        status=status,
        reason=reason,
        url=details.url,
        title=details.title,
        company=details.company,
        location=details.location,
        contact=details.contact,
        external_url=details.external_url,
        search_url=plan.search_url,
        keyword=plan.keyword,
        role_key=plan.role_key,
        selected_resume_role=choice.selected_role if choice else "",
        resume_path=choice.resume_path if choice else "",
        quick_apply=details.quick_apply,
        compatibility=compatibility,
        compatibility_threshold=compatibility_threshold,
        dry_run=dry_run,
        external=external,
        job_index=job_index,
    )


def run_bot(args, settings: Settings, loggers: BotLoggers) -> None:
    set_logger(loggers.llm)
    profiles = load_resume_profiles(settings, getattr(args, "resume", None))
    for profile in profiles:
        logging.info("Loaded resume (%d chars): role=%s path=%s", len(profile.text), profile.role_key, profile.path)
        loggers.run.info(
            "Loaded resume profile: role=%s keywords=%d embedding_dims=%d skills=%s",
            profile.role_key,
            len(profile.keywords),
            len(profile.embedding),
            ", ".join(profile.keywords[:25]) or "-",
        )
    if settings.llm.get("enabled"):
        logging.info("LLM features enabled (%s).", settings.llm.get("provider", "unknown"))

    search_plans = build_search_plans(settings, getattr(args, "search_url", None), getattr(args, "keywords", None))
    csv_store, question_store = create_storage(settings)
    csv_summary = csv_store.status_summary()
    question_summary = question_store.summary()
    job_backend = type(csv_store).__name__
    question_backend = type(question_store).__name__
    job_path = settings.logging.csv_log_path if job_backend == "CsvJobStore" else "postgres"
    question_path = settings.logging.question_memory_csv_path if question_backend == "QuestionMemoryStore" else "postgres"
    if csv_summary["total"]:
        logging.info(
            "Loaded job index: total=%d terminal_skips=%d retryable_failed=%d backend=%s path=%s",
            csv_summary["total"],
            csv_summary["terminal"],
            csv_summary["retryable_failed"],
            job_backend,
            job_path,
        )
        loggers.run.info(
            "Loaded job index: total=%d terminal_skips=%d retryable_failed=%d backend=%s path=%s",
            csv_summary["total"],
            csv_summary["terminal"],
            csv_summary["retryable_failed"],
            job_backend,
            job_path,
        )
    if question_summary["total"]:
        logging.info(
            "Loaded QA memory: total=%d verified=%d backend=%s path=%s",
            question_summary["total"],
            question_summary["verified"],
            question_backend,
            question_path,
        )
        loggers.run.info(
            "Loaded QA memory: total=%d verified=%d backend=%s path=%s",
            question_summary["total"],
            question_summary["verified"],
            question_backend,
            question_path,
        )

    browser = SeekBrowser(
        settings,
        headless=args.headless,
        user_data_dir=args.user_data_dir,
        profile_directory=args.profile_directory,
    ).start()
    try:
        browser.sign_in_if_needed(args.email, args.password, pause_for_login=not args.no_login_pause)
        page = browser.page
        assert page is not None
        apply_flow = ApplicationFlow(
            page,
            settings.raw,
            run_logger=loggers.run,
            action_logger=loggers.action,
            question_store=question_store,
        )

        applied = 0
        checked = 0
        seen_urls: set[str] = set()

        for plan in search_plans:
            if args.max > 0 and applied >= args.max:
                break
            page_url = plan.search_url
            pages_seen: set[str] = set()
            for _ in range(args.max_pages):
                if page_url in pages_seen:
                    break
                pages_seen.add(page_url)
                logging.info("Opening search URL: %s", page_url)
                loggers.run.info("Opening search URL: %s", page_url)
                page.goto(page_url, wait_until="domcontentloaded")
                cards = gather_job_cards(page)
                next_page_url = find_next_page_url(page)
                logging.info("Found %d candidate links on search page.", len(cards))
                loggers.run.info("Found %d candidate links on search page.", len(cards))

                for card in cards:
                    if args.max > 0 and applied >= args.max:
                        break
                    if card.url in seen_urls:
                        continue
                    indexed = csv_store.get(card.url)
                    if csv_store.should_skip(card.url):
                        seen_urls.add(card.url)
                        status = indexed.get("status", "") if indexed else ""
                        reason = indexed.get("reason", "") if indexed else ""
                        logging.info("Skipping indexed job: %s [%s:%s]", card.url, status, reason)
                        loggers.run.info(
                            "Skipping indexed job without reopening: title=%s url=%s status=%s reason=%s",
                            card.title,
                            card.url,
                            status,
                            reason,
                        )
                        continue
                    seen_urls.add(card.url)
                    checked += 1
                    if indexed and indexed.get("status") == "failed_apply":
                        loggers.run.info(
                            "Retrying previously failed application: title=%s url=%s previous_reason=%s",
                            card.title,
                            card.url,
                            indexed.get("reason", ""),
                        )
                    details = fetch_job_details(page, card.url)
                    logging.info("Evaluating (%d): %s", checked, details.title)
                    logging.info("Quick apply detected: %s", details.quick_apply)
                    loggers.run.info("Evaluating (%d): %s", checked, details.title)
                    loggers.run.info("Quick apply detected: %s", details.quick_apply)

                    if apply_flow.already_applied_notice():
                        csv_store.append(
                            _make_record(
                                status="already_applied",
                                reason="page_shows_applied",
                                details=details,
                                plan=plan,
                                choice=None,
                                compatibility_threshold=args.compatibility_threshold,
                                dry_run=args.dry_run,
                                external=False,
                                job_index=_extract_seek_job_id(details.url),
                            )
                        )
                        continue

                    if details.external_url and not details.quick_apply:
                        csv_store.append(
                            _make_record(
                                status="skipped_external",
                                reason="external_application",
                                details=details,
                                plan=plan,
                                choice=None,
                                compatibility_threshold=args.compatibility_threshold,
                                dry_run=args.dry_run,
                                external=True,
                                job_index=_extract_seek_job_id(details.url),
                            )
                        )
                        continue

                    if not details.quick_apply:
                        csv_store.append(
                            _make_record(
                                status="skipped_non_quick",
                                reason="not_quick_apply",
                                details=details,
                                plan=plan,
                                choice=None,
                                compatibility_threshold=args.compatibility_threshold,
                                dry_run=args.dry_run,
                                external=False,
                                job_index=_extract_seek_job_id(details.url),
                            )
                        )
                        continue

                    choice = choose_best_resume(plan.role_key, f"{details.title}\n{details.description}", profiles, settings.raw)
                    logging.info(
                        "Selected resume role: search_role=%s selected_resume_role=%s selection_scores=%s compatibility_scores=%s",
                        choice.search_role,
                        choice.selected_role,
                        ", ".join(f"{role}={score:.3f}" for role, score in choice.selection_scores),
                        ", ".join(f"{role}={score:.1f}" for role, score in choice.candidate_scores),
                    )
                    logging.info(
                        "Compatibility score: %.1f/10 semantic=%.1f raw_cosine=%.3f keyword=%.1f matched=%s missing=%s",
                        choice.compatibility.score,
                        choice.compatibility.semantic_score,
                        choice.compatibility.semantic_cosine,
                        choice.compatibility.keyword_score,
                        ", ".join(choice.compatibility.matched_keywords) or "-",
                        ", ".join(choice.compatibility.missing_keywords) or "-",
                    )
                    loggers.run.info(
                        "Selected resume role: search_role=%s selected_resume_role=%s selection_scores=%s compatibility_scores=%s",
                        choice.search_role,
                        choice.selected_role,
                        ", ".join(f"{role}={score:.3f}" for role, score in choice.selection_scores),
                        ", ".join(f"{role}={score:.1f}" for role, score in choice.candidate_scores),
                    )
                    loggers.run.info(
                        "Compatibility score: %.1f/10 semantic=%.1f raw_cosine=%.3f keyword=%.1f matched=%s missing=%s",
                        choice.compatibility.score,
                        choice.compatibility.semantic_score,
                        choice.compatibility.semantic_cosine,
                        choice.compatibility.keyword_score,
                        ", ".join(choice.compatibility.matched_keywords) or "-",
                        ", ".join(choice.compatibility.missing_keywords) or "-",
                    )
                    loggers.run.info(
                        "Compatibility extraction: job_keywords=%s resume_keywords=%s",
                        ", ".join(choice.compatibility.job_keywords) or "-",
                        ", ".join(choice.compatibility.resume_keywords) or "-",
                    )

                    if choice.compatibility.score <= args.compatibility_threshold:
                        csv_store.append(
                            _make_record(
                                status="skipped_compatibility",
                                reason="not_enough_compatibility_score",
                                details=details,
                                plan=plan,
                                choice=choice,
                                compatibility_threshold=args.compatibility_threshold,
                                dry_run=args.dry_run,
                                external=False,
                                job_index=_extract_seek_job_id(details.url),
                            )
                        )
                        continue

                    if settings.llm.get("enabled") and details.description:
                        details = replace(details, contact=_merge_contact(details.contact, extract_contact(details.description, settings.raw)))

                    success, reason = apply_flow.apply(details, choice, dry_run=args.dry_run)
                    if success:
                        applied += 1
                        csv_store.append(
                            _make_record(
                                status="applied",
                                reason="success",
                                details=details,
                                plan=plan,
                                choice=choice,
                                compatibility_threshold=args.compatibility_threshold,
                                dry_run=args.dry_run,
                                external=False,
                                job_index=_extract_seek_job_id(details.url),
                            )
                        )
                    else:
                        csv_store.append(
                            _make_record(
                                status="failed_apply",
                                reason=reason,
                                details=details,
                                plan=plan,
                                choice=choice,
                                compatibility_threshold=args.compatibility_threshold,
                                dry_run=args.dry_run,
                                external=False,
                                job_index=_extract_seek_job_id(details.url),
                            )
                        )
                if not next_page_url:
                    break
                page_url = next_page_url

        logging.info("Done.")
        loggers.run.info("Done.")
    finally:
        browser.close()
