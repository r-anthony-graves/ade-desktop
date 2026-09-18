"""The sections the rail lists. Only sections that EXIST are listed: a
greyed-out button for an unbuilt section reads as broken. Later pieces
(Ade, PM, QA, Path, Code) append to build_sections()."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget


@dataclass
class Section:
    name: str
    widget: QWidget
    start: Callable[[], None] | None = None
    stop: Callable[[], None] | None = None
    qss: str | None = None
    placeholder_reason: str | None = None


def placeholder(name: str, message: str) -> Section:
    label = QLabel(message)
    label.setObjectName("placeholder")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return Section(name, label, placeholder_reason=message)


def build_sections() -> list[Section]:
    from ade_desktop.sections.trader import build_trader_section, trader_root

    return [build_trader_section(trader_root())]
