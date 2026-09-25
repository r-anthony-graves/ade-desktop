"""The panel's message widgets. Plain Qt: QLabel's own Markdown renderer,
never a web view (Ray, 2026-09-17: "fully native, no browser engine").

Every connection here targets the widget's OWN methods, never the panel's
(the piece-1 lesson: a lambda or stored bound method that captures a window
makes it cyclic garbage the collector tears down at a random moment).
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout,
    QWidget,
)

ARGS_CLIP = 2000
SENDING = "Sending the decision…"
_STYLE = {
    "spin": "color:#d9772a; padding:4px 2px;",
    "user": "background:#2a3442;color:#e8ebef;border-radius:8px;padding:6px 10px;",
    "ade": "background:#1e2126;color:#d6d9de;border-radius:8px;padding:6px 10px;",
    "error": ("background:#3a1f22;color:#f0b4b4;border:1px solid #d95757;"
              "border-radius:8px;padding:6px 10px;"),
    "system": "color:#9aa1ab;padding:2px 4px;",
}


def _label(text, fmt, style, mono=False) -> QLabel:
    label = QLabel()
    label.setTextFormat(fmt)
    label.setText(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setOpenExternalLinks(False)   # links shown, not followed (spec)
    label.setStyleSheet(style)
    if mono:
        label.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    return label


def message_widget(msg: dict) -> QWidget:
    role = msg.get("role")
    kind = msg.get("kind")
    text = msg.get("text") or ""
    if kind == "approval":
        return ApprovalCard(msg)
    if kind == "working":
        # The avatar's spinner line (chat.html .sys.spin): amber, spaced.
        label = _label(text, Qt.TextFormat.PlainText, _STYLE["spin"])
        font = label.font()
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
        label.setFont(font)
        return label
    if role == "system":
        return _label(text, Qt.TextFormat.PlainText, _STYLE["system"])
    if kind == "error":
        return _label(text, Qt.TextFormat.PlainText, _STYLE["error"])
    if kind in ("shell", "inline"):
        return _label(text, Qt.TextFormat.PlainText,
                      _STYLE["ade" if role == "ade" else "user"], mono=True)
    if role == "user":
        return _label(text, Qt.TextFormat.PlainText, _STYLE["user"])
    return _label(text, Qt.TextFormat.MarkdownText, _STYLE["ade"])


class ApprovalCard(QFrame):
    """One approval. ONLY a click answers it: no default button, no
    auto-default, no keyboard focus -- a keystroke meant for the input box can
    never allow a tool call, or approve a change.

    Two shapes. A gated TOOL call is a turn already in flight, stopped part
    way, so the card names the tool and shows its arguments. An ESCALATION
    (Ade OS 2026-09-25) is a change Ade PROPOSES from a read-only turn, so the
    question is whether the work should happen at all -- and a tool name over
    a JSON blob does not ask it. Ray, 2026-09-25: "it should present as a
    review and approve."

    `kind` absent means "tool": every record was one before that date, and an
    older Ade OS sends no `kind`. A malformed escalation with no `prompt`
    falls back too, rather than offering an empty Approve.
    """

    decided = Signal(str, bool)   # approval id, allow

    def __init__(self, msg: dict, parent=None) -> None:
        super().__init__(parent)
        meta = msg.get("meta") or {}
        approval = meta.get("approval") or {}
        self.approval_id = str(approval.get("id") or "")
        card_args = approval.get("args") or {}
        self.escalation_prompt = str(card_args.get("prompt") or "").strip()
        self.is_escalation = bool(
            approval.get("kind") == "escalation" and self.escalation_prompt)
        self.setObjectName("approvalCard")
        self.setStyleSheet("QFrame#approvalCard{background:#2b2416;"
                           "border:1px solid #d9a441;border-radius:8px;}")
        box = QVBoxLayout(self)
        if self.is_escalation:
            title = QLabel("Ade wants to make a change — review and "
                           f"approve  ({self.approval_id})")
        else:
            title = QLabel(f"Approval needed: {approval.get('tool', '?')}  "
                           f"({self.approval_id})")
        title.setStyleSheet("color:#d9a441;font-weight:700;")
        title.setWordWrap(True)
        box.addWidget(title)
        if self.is_escalation:
            # The work in Ade's own words, and the root it would run in:
            # the two things a reviewer needs. Plain and wrapped -- a path is
            # not markdown, and a prompt runs to a sentence.
            what = _label(self.escalation_prompt, Qt.TextFormat.PlainText,
                          "color:#d6d9de;")
            what.setWordWrap(True)
            box.addWidget(what)
            root = card_args.get("root")
            if root:
                box.addWidget(_label(f"in {root}",
                                     Qt.TextFormat.PlainText,
                                     "color:#9aa1ab;", mono=True))
        else:
            full = json.dumps(card_args, indent=2, default=str)
            shown = full if len(full) <= ARGS_CLIP else full[:ARGS_CLIP] + "…"
            args = _label(shown, Qt.TextFormat.PlainText, "color:#d6d9de;", mono=True)
            args.setToolTip(full)
            box.addWidget(args)
        row = QHBoxLayout()
        self.allow = QPushButton("Approve" if self.is_escalation else "Allow")
        self.deny = QPushButton("Decline" if self.is_escalation else "Deny")
        for button in (self.allow, self.deny):
            button.setAutoDefault(False)
            button.setDefault(False)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(button)
        row.addStretch(1)
        box.addLayout(row)
        self.outcome = QLabel("")
        self.outcome.setStyleSheet("color:#9aa1ab;")
        box.addWidget(self.outcome)
        self.allow.clicked.connect(self._on_allow)
        self.deny.clicked.connect(self._on_deny)
        if meta.get("decided"):
            self.set_outcome(str(meta["decided"]), live=False)
        elif meta.get("moot"):
            self.set_outcome("Answered elsewhere", live=False)
        elif meta.get("deciding") is not None:
            # A decision is in flight. It lives in the MESSAGE, not only on
            # this widget, so a re-render cannot hand back live buttons and
            # let the same approval be answered twice (review finding).
            self.set_outcome(SENDING, live=False)
        else:
            self.outcome.hide()

    def _on_allow(self) -> None:
        self._click(True)

    def _on_deny(self) -> None:
        self._click(False)

    def _click(self, allow: bool) -> None:
        # Both, at once: no second click can ever send a second decision.
        self.allow.setEnabled(False)
        self.deny.setEnabled(False)
        self.decided.emit(self.approval_id, allow)

    def set_outcome(self, text: str, live: bool) -> None:
        self.outcome.setText(text)
        self.outcome.show()
        for button in (self.allow, self.deny):
            button.setVisible(live)
            button.setEnabled(live)


class SkillChips(QWidget):
    """The attached skills, above the input. Clicking a chip detaches it."""

    removed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.addStretch(1)
        self._buttons: list[QToolButton] = []
        self.hide()

    def chip_buttons(self) -> list[QToolButton]:
        return list(self._buttons)

    def set_skills(self, names) -> None:
        for button in self._buttons:
            self._row.removeWidget(button)
            button.deleteLater()
        self._buttons = []
        for name in names:
            chip = QToolButton()
            chip.setText(f"{name}  ×")
            chip.setToolTip(f"Detach {name}")
            chip.setProperty("skill", name)
            chip.setStyleSheet("QToolButton{background:#262b33;border:1px solid "
                               "#333a45;border-radius:9px;padding:2px 8px;"
                               "color:#d6d9de;}")
            chip.clicked.connect(self._chip_clicked)
            self._row.insertWidget(self._row.count() - 1, chip)
            self._buttons.append(chip)
        self.setVisible(bool(self._buttons))

    def _chip_clicked(self) -> None:
        chip = self.sender()
        if chip is not None:
            self.removed.emit(str(chip.property("skill")))
