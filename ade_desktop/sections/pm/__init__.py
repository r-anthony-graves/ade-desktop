"""PM (piece 4): projects, the PMI package, backlog, risks and the
monitoring cycle -- Ade OS's /v1/pm/* routes, natively."""

from __future__ import annotations


def build_pm_section(active):
    from ade_desktop.sections import Section
    from ade_desktop.sections.pm.client import PmClient
    from ade_desktop.sections.pm.panel import PmPanel
    from ade_desktop.workspace.files import FilesClient

    pm, files = PmClient(), FilesClient()
    panel = PmPanel(pm, files, active)
    # The clients are the panel's children in all but name: stopping them
    # means no result arrives at a panel that is going away.
    pm.setParent(panel)
    files.setParent(panel)
    return Section("PM", panel, stop=panel.stop_clients)
