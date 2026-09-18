"""PM's pure rules, each with one home that this mirrors:

    slug()            adeos/records/pmi.py python_slug == the web's packageSlug
    PROJECT_STATES    adeos/records/store.py PROJECT_STATES
    PMI docs          the intake reply's `artifacts` (pmi.py ARTIFACTS); README.md
                      is never authored (author_doc rejects it)
    QA_DOCS           the web's SECTION_FILE, in its order
    grading           the web's AddProjectPanel: zero on disk is STALE, never ok
"""

from __future__ import annotations

import re

PROJECT_STATES = ("active", "complete", "not_started", "ongoing", "done", "archived")
BACKLOG_ACTIONS = ("complete", "promote", "drop")
RISK_LEVELS = ("low", "medium", "high")
QA_DOCS = ("requirements.md", "test_plan.md", "test_suites.md", "test_cases.md",
           "defects_seed.md", "traceability.md", "reports.md", "test_data.md",
           "automation.md", "api_testing.md", "performance.md", "security.md",
           "analytics.md")
FILLED = re.compile(r"^Fill status: filled$", re.M)
SEVERITY_ORDER = {"act": 0, "check": 1}


def slug(name: str) -> str:
    """python_slug, step for step -- including the pinned quirk that a
    dotted NAME loses its "extension" ("v2.0 rewrite" -> "v2")."""
    base = re.sub(r"^.*[\\/]", "", name or "")
    base = re.sub(r"\.[^.]+$", "", base)
    s = re.sub(r"[^a-z0-9]+", "-", base.lower())
    s = s.strip("-")[:48]
    return s or "requirements"


def format_status(status: str) -> str:
    return (status or "").replace("_", " ")


def visible(projects: list[dict], show_archived: bool) -> list[dict]:
    return list(projects) if show_archived else [
        p for p in projects if p.get("status") != "archived"]


def pick(projects: list[dict], name: str) -> dict | None:
    """The named project if it is showing, else the first one showing: an
    unknown or hidden name opens the page, never blanks it (the web's rule)."""
    for p in projects:
        if p.get("name") == name:
            return p
    return projects[0] if projects else None


def empty_label(projects: list[dict], show_archived: bool) -> str:
    hidden = sum(1 for p in projects if p.get("status") == "archived")
    if not show_archived and hidden and not visible(projects, False):
        return f"No visible projects — {hidden} archived"
    return "No projects."


def pm_docs(artifacts: list[str]) -> list[str]:
    return [a.split("/")[-1] for a in artifacts if a.split("/")[-1] != "README.md"]


def pm_paths(artifacts: list[str]) -> list[str]:
    return [a for a in artifacts if a.split("/")[-1] != "README.md"]


def is_filled(text: str) -> bool:
    return bool(FILLED.search(text or ""))


def grade_pm(filled: int, total: int) -> tuple[str, str]:
    if filled == 0:
        return ("stale", "reported done but files unchanged — every doc still says skeleton")
    return ("ok", f"{total}/{total} documents authored, {filled}/{total} filled on disk")


def grade_qa(files: int, total: int, qa_dir: str) -> tuple[str, str]:
    if files == 0:
        return ("stale", "reported done but files unchanged — qa directory is empty")
    return ("ok", f"{total}/{total} documents authored, "
                  f"{files} file{'' if files == 1 else 's'} on disk under {qa_dir}/")


def for_project(rows: list[dict], name: str) -> list[dict]:
    return [r for r in rows if r.get("project") == name]


def sort_findings(findings: list[dict]) -> list[dict]:
    return sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 9))


def name_from_file(filename: str) -> str:
    return slug(filename).replace("-", " ")


def name_from_paste(text: str) -> str:
    m = re.search(r"^#{1,6}\s+(.+)$", text or "", re.M)
    return m.group(1).strip() if m else ""


def summarise_findings(summary: dict) -> str:
    n = int((summary or {}).get("findings") or 0)
    if not n:
        return "Healthy: the monitoring cycle found nothing."
    act = int((summary or {}).get("needs_action") or 0)
    return (f"{n} finding{'' if n == 1 else 's'}"
            + (f", {act} need{'s' if act == 1 else ''} action" if act else ""))
