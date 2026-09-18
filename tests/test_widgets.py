"""Message widgets: Qt's own Markdown (no web view), links not followed, and
an approval card that only a CLICK can answer."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QLabel

from ade_desktop.conversation.widgets import ApprovalCard, SkillChips, message_widget


def _approval(meta_extra=None):
    meta = {"approval": {"id": "a1", "tool": "write_file",
                         "args": {"path": "x.txt"}}}
    meta.update(meta_extra or {})
    return {"role": "ade", "kind": "approval", "text": "", "meta": meta}


def test_ade_replies_are_markdown_and_links_are_not_followed(qapp):
    w = message_widget({"role": "ade", "kind": "ask", "text": "**bold** [x](http://e)"})
    assert isinstance(w, QLabel)
    assert w.textFormat() == Qt.TextFormat.MarkdownText
    assert w.openExternalLinks() is False


def test_shell_output_is_monospace_plain_text(qapp):
    w = message_widget({"role": "ade", "kind": "shell", "text": "a  b"})
    assert w.textFormat() == Qt.TextFormat.PlainText
    fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    assert w.font().family() == fixed.family()


def test_user_and_error_text_is_plain(qapp):
    for kind, role in (("ask", "user"), ("error", "ade"), ("text", "system")):
        w = message_widget({"role": role, "kind": kind, "text": "**not bold**"})
        assert w.textFormat() == Qt.TextFormat.PlainText


def test_an_approval_can_only_be_clicked(qapp):
    """Neither Enter nor any default-button behaviour may answer an
    approval: a keystroke meant for the input box must never allow a tool."""
    card = ApprovalCard(_approval())
    for b in (card.allow, card.deny):
        assert b.isEnabled() and not b.isDefault() and not b.autoDefault()
        assert b.focusPolicy() == Qt.FocusPolicy.NoFocus
    got = []
    card.decided.connect(lambda aid, allow: got.append((aid, allow)))
    card.allow.click()
    assert got == [("a1", True)]
    assert not card.allow.isEnabled() and not card.deny.isEnabled()


def test_outcomes(qapp):
    card = ApprovalCard(_approval())
    card.deny.click()
    card.set_outcome("Could not decide a1: HTTP 500", live=True)
    assert card.allow.isEnabled() and card.deny.isEnabled()
    card.set_outcome("Already decided elsewhere", live=False)
    assert card.outcome.text() == "Already decided elsewhere"
    assert card.allow.isHidden() and card.deny.isHidden()


def test_restored_cards_are_never_live(qapp):
    decided = ApprovalCard(_approval({"decided": "Allowed a1"}))
    assert decided.allow.isHidden() and decided.outcome.text() == "Allowed a1"
    moot = ApprovalCard(_approval({"moot": True}))
    assert moot.allow.isHidden() and moot.outcome.text() == "Answered elsewhere"


def test_skill_chips(qapp):
    chips = SkillChips()
    chips.set_skills(["a", "b"])
    buttons = chips.chip_buttons()
    assert [b.property("skill") for b in buttons] == ["a", "b"]
    removed = []
    chips.removed.connect(removed.append)
    buttons[0].click()
    assert removed == ["a"]
    chips.set_skills([])
    assert chips.isHidden()
