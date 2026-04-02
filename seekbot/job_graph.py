import logging
import re
from dataclasses import replace
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from seekbot.domain import ApplicationRecord, ContactInfo, JobCard, JobDetails, ResumeChoice, ResumeProfile, SearchPlan
from seekbot.llm import extract_contact
from seekbot.seek.application import ApplicationFlow
from seekbot.seek.search import fetch_job_details


def _merge_contact(original: ContactInfo, llm_contact: dict | None) -> ContactInfo:
    if not llm_contact:
        return original
    return ContactInfo(
        name=original.name or llm_contact.get("name", ""),
        email=original.email or llm_contact.get("email", ""),
        phone=original.phone or llm_contact.get("phone", ""),
    )


def extract_seek_job_id(url: str) -> str:
    match = re.search(r"/job/(\d+)", url or "")
    return match.group(1) if match else ""


def build_application_record(
    *,
    status: str,
    reason: str,
    details: JobDetails,
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


class JobState(TypedDict, total=False):
    plan: SearchPlan
    card: JobCard
    checked: int
    details: JobDetails
    choice: ResumeChoice
    status: str
    reason: str
    external: bool
    success: bool
    job_index: str


class JobGraphRunner:
    def __init__(
        self,
        *,
        config: dict,
        run_logger,
        job_store,
        apply_flow: ApplicationFlow,
        profiles: list[ResumeProfile],
        compatibility_threshold: float,
        dry_run: bool,
        choose_best_resume_fn,
    ):
        self.config = config
        self.run_logger = run_logger
        self.job_store = job_store
        self.apply_flow = apply_flow
        self.profiles = profiles
        self.compatibility_threshold = compatibility_threshold
        self.dry_run = dry_run
        self.choose_best_resume = choose_best_resume_fn
        self.graph = self._build_graph()

    def _log_stage(self, message: str, *args) -> None:
        logging.info(message, *args)
        if self.run_logger:
            self.run_logger.info(message, *args)

    def _log_node(self, node_name: str, state: JobState) -> None:
        labels = {
            "fetch_details": "fetching job details",
            "classify_job": "checking apply path",
            "choose_resume": "selecting resume",
            "gate_compatibility": "checking compatibility threshold",
            "enrich_contact": "extracting recruiter contact",
            "apply_job": "starting application flow",
            "persist_result": "recording result",
        }
        card = state.get("card")
        details = state.get("details")
        title = details.title if details else (card.title if card else "")
        url = details.url if details else (card.url if card else "")
        if self.run_logger:
            self.run_logger.info("Job stage: %s title=%s url=%s", labels.get(node_name, node_name), title, url)

    def _build_graph(self):
        graph = StateGraph(JobState)
        graph.add_node("fetch_details", self._fetch_details)
        graph.add_node("classify_job", self._classify_job)
        graph.add_node("choose_resume", self._choose_resume)
        graph.add_node("gate_compatibility", self._gate_compatibility)
        graph.add_node("enrich_contact", self._enrich_contact)
        graph.add_node("apply_job", self._apply_job)
        graph.add_node("persist_result", self._persist_result)

        graph.add_edge(START, "fetch_details")
        graph.add_edge("fetch_details", "classify_job")
        graph.add_conditional_edges(
            "classify_job",
            self._route_after_classify,
            {
                "persist_result": "persist_result",
                "choose_resume": "choose_resume",
            },
        )
        graph.add_edge("choose_resume", "gate_compatibility")
        graph.add_conditional_edges(
            "gate_compatibility",
            self._route_after_compatibility,
            {
                "persist_result": "persist_result",
                "enrich_contact": "enrich_contact",
            },
        )
        graph.add_edge("enrich_contact", "apply_job")
        graph.add_edge("apply_job", "persist_result")
        graph.add_edge("persist_result", END)
        return graph.compile()

    def process(self, plan: SearchPlan, card: JobCard, checked: int) -> JobState:
        return self.graph.invoke({"plan": plan, "card": card, "checked": checked})

    def _fetch_details(self, state: JobState) -> JobState:
        self._log_node("fetch_details", state)
        card = state["card"]
        details = fetch_job_details(self.apply_flow.page, card.url)
        checked = int(state.get("checked", 0) or 0)
        logging.info("Evaluating (%d): %s", checked, details.title)
        logging.info("Quick apply detected: %s", details.quick_apply)
        self.run_logger.info("Evaluating (%d): %s", checked, details.title)
        self.run_logger.info("Quick apply detected: %s", details.quick_apply)
        return {"details": details, "job_index": extract_seek_job_id(details.url), "external": False}

    def _classify_job(self, state: JobState) -> JobState:
        self._log_node("classify_job", state)
        details = state["details"]
        if self.apply_flow.already_applied_notice():
            return {"status": "already_applied", "reason": "page_shows_applied", "external": False}
        if details.external_url and not details.quick_apply:
            return {"status": "skipped_external", "reason": "external_application", "external": True}
        if not details.quick_apply:
            return {"status": "skipped_non_quick", "reason": "not_quick_apply", "external": False}
        return {"status": "ready_for_resume"}

    def _route_after_classify(self, state: JobState) -> str:
        if state.get("status") in {"already_applied", "skipped_external", "skipped_non_quick"}:
            return "persist_result"
        return "choose_resume"

    def _choose_resume(self, state: JobState) -> JobState:
        self._log_node("choose_resume", state)
        details = state["details"]
        plan = state["plan"]
        choice = self.choose_best_resume(plan.role_key, f"{details.title}\n{details.description}", self.profiles, self.config)
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
        self.run_logger.info(
            "Selected resume role: search_role=%s selected_resume_role=%s selection_scores=%s compatibility_scores=%s",
            choice.search_role,
            choice.selected_role,
            ", ".join(f"{role}={score:.3f}" for role, score in choice.selection_scores),
            ", ".join(f"{role}={score:.1f}" for role, score in choice.candidate_scores),
        )
        self.run_logger.info(
            "Compatibility score: %.1f/10 semantic=%.1f raw_cosine=%.3f keyword=%.1f matched=%s missing=%s",
            choice.compatibility.score,
            choice.compatibility.semantic_score,
            choice.compatibility.semantic_cosine,
            choice.compatibility.keyword_score,
            ", ".join(choice.compatibility.matched_keywords) or "-",
            ", ".join(choice.compatibility.missing_keywords) or "-",
        )
        self.run_logger.info(
            "Compatibility extraction: job_keywords=%s resume_keywords=%s",
            ", ".join(choice.compatibility.job_keywords) or "-",
            ", ".join(choice.compatibility.resume_keywords) or "-",
        )
        return {"choice": choice, "status": "ready_for_compatibility"}

    def _gate_compatibility(self, state: JobState) -> JobState:
        self._log_node("gate_compatibility", state)
        choice = state["choice"]
        if choice.compatibility.score <= self.compatibility_threshold:
            return {"status": "skipped_compatibility", "reason": "not_enough_compatibility_score", "external": False}
        return {"status": "ready_for_contact"}

    def _route_after_compatibility(self, state: JobState) -> str:
        if state.get("status") == "skipped_compatibility":
            return "persist_result"
        return "enrich_contact"

    def _enrich_contact(self, state: JobState) -> JobState:
        self._log_node("enrich_contact", state)
        details = state["details"]
        if self.config.get("llm", {}).get("enabled") and details.description:
            self._log_stage("Application stage: extracting recruiter contact for %s", details.title)
            details = replace(details, contact=_merge_contact(details.contact, extract_contact(details.description, self.config)))
            self._log_stage("Application stage: recruiter contact step finished for %s", details.title)
        return {"details": details}

    def _apply_job(self, state: JobState) -> JobState:
        self._log_node("apply_job", state)
        details = state["details"]
        choice = state["choice"]
        self._log_stage("Application stage: starting application for %s", details.title)
        success, reason = self.apply_flow.apply(details, choice, dry_run=self.dry_run)
        if success:
            return {"status": "applied", "reason": "success", "success": True, "external": False}
        return {"status": "failed_apply", "reason": reason, "success": False, "external": False}

    def _persist_result(self, state: JobState) -> JobState:
        self._log_node("persist_result", state)
        details = state["details"]
        plan = state["plan"]
        choice = state.get("choice")
        record = build_application_record(
            status=state["status"],
            reason=state.get("reason", ""),
            details=details,
            plan=plan,
            choice=choice,
            compatibility_threshold=self.compatibility_threshold,
            dry_run=self.dry_run,
            external=bool(state.get("external", False)),
            job_index=state.get("job_index", ""),
        )
        self.job_store.append(record)
        self._log_stage(
            "Job result: title=%s status=%s reason=%s",
            details.title,
            state["status"],
            state.get("reason", ""),
        )
        return state
