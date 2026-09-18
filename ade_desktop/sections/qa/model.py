"""QA's catalogue and rules.

catalogue.json is the web's QA_SECTIONS (adeos/web/src/pages/QA/qaNav.ts),
exported verbatim on 2026-09-18 -- labels, purposes and areas -- so the two
desks describe the same thing. SECTION_FILE is the web's SectionArtifact
map: 13 sections map 1:1 onto the QA package; dashboard, test execution and
settings have no file on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path

SECTIONS: list[dict] = json.loads(
    (Path(__file__).with_name("catalogue.json")).read_text(encoding="utf-8"))
SECTION_FILE = {
    "requirements": "requirements.md", "test-plans": "test_plan.md",
    "test-suites": "test_suites.md", "test-cases": "test_cases.md",
    "defects": "defects_seed.md", "traceability": "traceability.md",
    "reports": "reports.md", "test-data": "test_data.md",
    "automation": "automation.md", "api-testing": "api_testing.md",
    "performance": "performance.md", "security": "security.md",
    "analytics": "analytics.md",
}
# The web's five, used only when /v1/agents cannot say what qa takes today.
FALLBACK_TYPES = ("test", "verify", "regress", "analyse_bug", "generate_artifacts")


def section(section_id: str) -> dict:
    return next((s for s in SECTIONS if s["id"] == section_id), SECTIONS[0])


def board_text(sec: dict) -> str:
    lines = [sec.get("purpose", "")]
    for area in sec.get("areas") or []:
        lines.append(f"{area.get('title')}: " + ", ".join(area.get("items") or []))
    return "\n\n".join(l for l in lines if l)


def artifact_path(slug: str, section_id: str) -> str | None:
    file = SECTION_FILE.get(section_id)
    return f"qa/{slug}/{file}" if slug and file else None


def package_rows(listing_names: set[str]) -> list[tuple[str, str, bool]]:
    """(section label, file, present?) for the 13 documents, in rail order."""
    rows = []
    for sec in SECTIONS:
        file = SECTION_FILE.get(sec["id"])
        if file:
            rows.append((sec["label"], file, file in listing_names))
    return rows


def qa_types(agents_result) -> list[str]:
    """The qa primary's task types from /v1/agents, or the web's five."""
    if isinstance(agents_result, dict) and "error" not in agents_result:
        for agent in agents_result.get("agents") or []:
            if isinstance(agent, dict) and agent.get("name") == "qa":
                types = [t for t in agent.get("task_types") or [] if isinstance(t, str)]
                if types:
                    return types
    return list(FALLBACK_TYPES)
