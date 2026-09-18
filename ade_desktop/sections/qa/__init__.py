"""QA (piece 5): the web's QA desk over the active project's qa/<slug>/
package, generation through /v1/pm/author, and qa task dispatch."""

from __future__ import annotations


def build_qa_section(active):
    from ade_desktop.sections import Section
    from ade_desktop.sections.pm.client import PmClient
    from ade_desktop.sections.qa.client import QaClient
    from ade_desktop.sections.qa.panel import QaPanel
    from ade_desktop.workspace.files import FilesClient

    qa, pm, files = QaClient(), PmClient(), FilesClient()
    panel = QaPanel(qa, pm, files, active)
    for client in (qa, pm, files):
        client.setParent(panel)
    return Section("QA", panel, stop=panel.stop_clients)
