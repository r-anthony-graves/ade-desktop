"""The Chat thread as /v1/ask history -- the avatar's threadHistory(), and
the same 40 x 4000 the server sanitises to."""

from ade_desktop.conversation.history import thread_history


def m(role, text, kind="ask"):
    return {"role": role, "kind": kind, "text": text}


def test_roles_and_skips():
    msgs = [m("system", "note", "text"), m("user", "q1"), m("ade", "a1"),
            m("ade", "", "ask"), m("system", "Working…", "working"),
            m("user", "q2")]
    assert thread_history(msgs) == [{"role": "user", "content": "q1"},
                                    {"role": "assistant", "content": "a1"}]


def test_long_text_is_cut_to_4000_plus_ellipsis():
    out = thread_history([m("user", "x" * 5000), m("ade", "ok")])
    assert out[0]["content"] == "x" * 4000 + "…"


def test_keeps_the_last_40():
    msgs = []
    for i in range(30):
        msgs += [m("user", f"q{i}"), m("ade", f"a{i}")]
    out = thread_history(msgs)
    assert len(out) == 40
    assert out[-1]["content"] == "a29" and out[0]["content"] == "q10"
