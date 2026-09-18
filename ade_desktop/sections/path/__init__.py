"""The Path (piece 6): Ray's separate project, reached over its own JSON
face on `thepath serve` -- nothing of it lives here."""

from __future__ import annotations


def build_path_section():
    from ade_desktop.sections import Section
    from ade_desktop.sections.path.client import PathClient
    from ade_desktop.sections.path.panel import PathPanel

    client = PathClient()
    panel = PathPanel(client)
    client.setParent(panel)
    return Section("Path", panel, stop=panel.stop_clients)
