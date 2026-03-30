from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchPlan:
    role_key: str
    keyword: str | None
    search_url: str


@dataclass(frozen=True)
class ResumeProfile:
    role_key: str
    path: str
    text: str
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContactInfo:
    name: str = ""
    email: str = ""
    phone: str = ""


@dataclass(frozen=True)
class JobCard:
    title: str
    url: str


@dataclass(frozen=True)
class JobDetails:
    title: str
    url: str
    description: str
    company: str
    location: str
    quick_apply: bool
    external_url: str = ""
    contact: ContactInfo = field(default_factory=ContactInfo)


@dataclass(frozen=True)
class CompatibilityResult:
    score: float
    matched_keywords: list[str]
    missing_keywords: list[str]
    resume_keywords: list[str]
    job_keywords: list[str]


@dataclass(frozen=True)
class ResumeChoice:
    search_role: str
    selected_role: str
    resume_path: str
    resume_text: str
    compatibility: CompatibilityResult
    candidate_scores: list[tuple[str, float]]


@dataclass(frozen=True)
class ApplicationRecord:
    status: str
    reason: str
    url: str
    title: str
    company: str
    location: str
    contact: ContactInfo
    external_url: str
    search_url: str
    keyword: str | None
    role_key: str
    selected_resume_role: str
    resume_path: str
    quick_apply: bool
    compatibility: CompatibilityResult | None
    compatibility_threshold: float
    dry_run: bool
    external: bool
    job_index: str
