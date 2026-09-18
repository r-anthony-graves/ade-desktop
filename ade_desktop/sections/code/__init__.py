"""Code (piece 7): the workspace tree, editor tabs, Problems and a terminal,
in place of the web's VS Code frame."""

from __future__ import annotations


def build_code_section():
    from ade_desktop.sections import Section
    from ade_desktop.sections.code.client import CodeClient
    from ade_desktop.sections.code.panel import CodePanel
    from ade_desktop.workspace.files import FilesClient

    client, files = CodeClient(), FilesClient()
    panel = CodePanel(client, files)
    for c in (client, files):
        c.setParent(panel)
    return Section("Code", panel, stop=panel.stop_clients)
