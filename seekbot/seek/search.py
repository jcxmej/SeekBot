import re
import urllib.parse

from playwright.sync_api import Page

from seekbot.domain import ContactInfo, JobCard, JobDetails

SEEK_BASE_URL = "https://www.seek.com.au"
SEEK_SEARCH_PATH = "/jobs"


def build_search_urls(keywords: list[str], location: str = "") -> list[str]:
    urls: list[str] = []
    for keyword in keywords:
        query = {"keywords": keyword}
        if location.strip():
            query["location"] = location.strip()
        urls.append(f"{SEEK_BASE_URL}{SEEK_SEARCH_PATH}?{urllib.parse.urlencode(query)}")
    return urls


def normalize_job_url(url: str) -> str:
    if not url:
        return url
    if url.startswith("/"):
        url = urllib.parse.urljoin(SEEK_BASE_URL, url)
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def is_seek_domain_url(url: str) -> bool:
    if not url:
        return False
    if url.startswith("/"):
        return True
    return "seek.com.au" in urllib.parse.urlsplit(url).netloc.lower()


def _body_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=4000)
    except Exception:
        return ""


def gather_job_cards(page: Page) -> list[JobCard]:
    anchors = page.locator("a[href*='/job/']")
    seen: set[str] = set()
    cards: list[JobCard] = []
    for index in range(anchors.count()):
        anchor = anchors.nth(index)
        href = anchor.get_attribute("href") or ""
        if not href:
            continue
        normalized = normalize_job_url(href)
        if normalized in seen:
            continue
        text = (anchor.inner_text(timeout=1000) or "").strip()
        if not text:
            text = (anchor.get_attribute("aria-label") or "").strip()
        if not text:
            text = (anchor.get_attribute("title") or "").strip()
        if not text:
            text = "(no title)"
        seen.add(normalized)
        cards.append(JobCard(title=text, url=normalized))
    return cards


def find_next_page_url(page: Page) -> str | None:
    selectors = ["a[rel='next']", "a[aria-label*='Next' i]", "a[title*='Next' i]"]
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count():
            href = locator.first.get_attribute("href") or ""
            if href:
                return urllib.parse.urljoin(SEEK_BASE_URL, href)
    return None


def extract_contact_info(text: str) -> ContactInfo:
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text or "")
    phone_match = re.search(r"(\+?\d[\d\s().-]{7,}\d)", text or "")
    name_match = re.search(
        r"(?:contact|recruiter|hiring manager|talent|hr)\s*[:\-]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
        text or "",
    )
    return ContactInfo(
        name=name_match.group(1).strip() if name_match else "",
        email=email_match.group(0).strip() if email_match else "",
        phone=phone_match.group(1).strip() if phone_match else "",
    )


def find_external_application_url(page: Page) -> str:
    selectors = [
        "a[aria-label*='apply' i]",
        "a[title*='apply' i]",
        "a[data-automation*='apply']",
    ]
    for selector in selectors:
        anchors = page.locator(selector)
        for index in range(anchors.count()):
            href = anchors.nth(index).get_attribute("href") or ""
            if href and not is_seek_domain_url(href):
                return href
    apply_links = page.get_by_role("link", name=re.compile(r"apply", re.I))
    for index in range(apply_links.count()):
        href = apply_links.nth(index).get_attribute("href") or ""
        if href and not is_seek_domain_url(href):
            return href
    return ""


def fetch_job_details(page: Page, job_url: str) -> JobDetails:
    page.goto(job_url, wait_until="domcontentloaded")
    body_text = _body_text(page)

    title = ""
    for selector in ["h1", "[data-automation='jobTitle']", "header h1"]:
        locator = page.locator(selector)
        if locator.count():
            title = (locator.first.inner_text(timeout=1000) or "").strip()
            if title:
                break

    description_candidates: list[str] = []
    for selector in [".job-description", ".job__description", "#job-description", "article", "main"]:
        locator = page.locator(selector)
        if locator.count():
            try:
                description_candidates.append(locator.first.inner_text(timeout=1000))
            except Exception:
                continue
    description = max(description_candidates, key=len) if description_candidates else body_text

    company = ""
    for selector in [
        "[data-automation='advertiser-name']",
        "[data-automation='advertiser-name-with-logo']",
        ".advertiser-name",
    ]:
        locator = page.locator(selector)
        if locator.count():
            company = (locator.first.inner_text(timeout=1000) or "").strip()
            if company:
                break

    location = ""
    for selector in ["[data-automation='jobLocation']", "[data-automation='job-location']", ".job-location"]:
        locator = page.locator(selector)
        if locator.count():
            location = (locator.first.inner_text(timeout=1000) or "").strip()
            if location:
                break

    quick_apply = page.get_by_role("link", name=re.compile("quick apply", re.I)).count() > 0
    if not quick_apply:
        quick_apply = "quick apply" in body_text.lower()

    external_url = find_external_application_url(page)

    return JobDetails(
        title=title or "(no title)",
        url=job_url,
        description=description or body_text,
        company=company,
        location=location,
        quick_apply=quick_apply,
        external_url=external_url,
        contact=extract_contact_info(description or body_text),
    )
