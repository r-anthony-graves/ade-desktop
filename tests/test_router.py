"""Where a typed line goes. Pure; ported from the avatar's classify() and
routePlain()."""

from ade_desktop.conversation.router import Route, looks_like_clear, route

CMDS = frozenset({"help", "clear", "health"})


def r(raw, tab="chat"):
    return route(raw, tab, CMDS)


def test_prefixes():
    assert r("!git status") == Route("shell", "git status")
    assert r("?what brain") == Route("chat", "what brain")
    assert r("/coding fix it") == Route("task", "fix it", type="coding")
    assert r("/Coding fix it") == Route("task", "fix it", type="coding")
    assert r("/help") == Route("command", "", verb="help")
    assert r("/clear now") == Route("command", "now", verb="clear")


def test_skill_and_upload_verbs():
    assert r("/skill ade-brainstorming") == Route(
        "skill", "ade-brainstorming", verb="skill")
    assert r("/SUPERPOWERS") == Route("skill", "", verb="superpowers")
    assert r("/upload folder") == Route("upload", "folder", verb="upload")


def test_a_dropped_command_name_is_a_task_type():
    """/gpu used to print 'no dedicated GPU' on a two-RTX machine. Now it is
    just a word Ade OS does not serve as a task type -- it fails loudly."""
    assert r("/gpu") == Route("task", "", type="gpu")


def test_plain_lines_on_chat():
    assert r("what is in glyph.js").kind == "ask"
    assert r("git status") == Route("inline_shell", "git status")
    assert r("clear the chat") == Route("clear", "clear the chat")


def test_plain_lines_on_shell_are_shell():
    assert r("hello there", tab="shell") == Route("shell", "hello there")
    assert r("?still chat", tab="shell").kind == "chat"


def test_empty():
    assert r("   ").kind == "empty"
    assert r("!") == Route("shell", "")


def test_looks_like_clear():
    for yes in ("clear", "clear context", "please clear the chat",
                "reset the conversation", "new chat", "start a new thread",
                "ESCALATE: clear the context",
                "user requested to clear everything"):
        assert looks_like_clear(yes), yes
    for no in ("clear the screen", "clearly not", "what is new", "forget it"):
        assert not looks_like_clear(no), no
