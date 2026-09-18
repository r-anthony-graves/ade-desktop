"""Reply text, ported from the avatar's readReply(), applyAskResult() and
its /health formatter."""

from ade_desktop.conversation.replies import ask_reply, health_text, read_reply


def test_read_reply_order():
    assert read_reply({"choices": [{"message": {"content": "hi"}}]}) == "hi"
    assert read_reply({"summary": "s", "output": "o"}) == "o"
    assert read_reply({"error": "e"}) == "e"
    assert read_reply({"task_id": "abc"}) == "task abc accepted"
    assert read_reply("plain") == "plain"
    assert read_reply(None) == ""
    assert read_reply({"x": 1}) == '{\n  "x": 1\n}'


def test_ask_reply_plain_and_cited():
    assert ask_reply({"answer": "A"}).text == "A"
    assert ask_reply({"answer": "A", "roots_cited": ["ade-ai"]}).text == \
        "A\n\nFrom: ade-ai"
    assert ask_reply({}).text == "(no output)"


def test_ask_reply_escalate_stays_here_and_stages_nothing():
    r = ask_reply({"answer": "ESCALATE: add a flag",
                   "escalate": {"prompt": "add a flag", "root": "ade-ai"}})
    assert r.text == ("add a flag\n\nAde would treat this as a change in "
                      "ade-ai. It stays here — nothing was staged.")
    assert r.cleared is False
    assert ask_reply({"answer": "hi",
                      "escalate": {"prompt": "greet Ray"}}).text == "Hello, Ray."
    cleared = ask_reply({"answer": "",
                         "escalate": {"prompt": "clear the context"}})
    assert cleared.cleared is True


def test_health_text():
    up = {"status": "up", "may_execute_tools": True,
          "subsystems": {"memory": {"up": True, "detail": "pg"}}}
    assert health_text(up) == "Ade OS: up\n  memory: up - pg"
    blocked = {"status": "down", "may_execute_tools": False,
               "blocking_reason": "db", "subsystems": {"memory": {"up": False}}}
    assert health_text(blocked) == \
        "Ade OS: down\n  memory: DOWN\n  tools BLOCKED: db"
    assert health_text({"error": "ConnectError: refused"}) == (
        "Ade OS did not answer /v1/health - ConnectError: refused. "
        "That IS the health answer: the API is unreachable.")
