"""Reply text, ported from the avatar's readReply(), applyAskResult() and
its /health formatter."""

from ade_desktop.conversation.replies import (
    ask_reply, error_cause, health_text, read_reply, task_types_from,
)


def test_error_cause_wording():
    assert error_cause({"error": "ConnectError: refused"}) == \
        "Ade OS unreachable: ConnectError: refused"
    assert error_cause({"error": "ReadTimeout: timed out"}) == \
        "no answer in time: ReadTimeout: timed out"
    assert error_cause({"error": "HTTP 502: not JSON", "status": 502}) == \
        "HTTP 502: not JSON"
    assert error_cause({"error": {"code": "execution_blocked",
                                  "message": "memory down"},
                        "status": 503}) == \
        "HTTP 503: execution_blocked - memory down"


def test_a_reachable_server_is_never_called_unreachable():
    """Review finding: Ade OS returns some errors as plain strings -- the 409
    'session busy' from /v1/terminal/run, a 200 {ok:false, error} from
    /v1/terminal. It answered; it is not 'unreachable'."""
    assert error_cause({"error": "session busy", "status": 409}) == \
        "HTTP 409: session busy"
    assert error_cause({"ok": False, "error": "timed out after 30s"}) == \
        "Ade OS said: timed out after 30s"
    assert error_cause({"error": "RemoteProtocolError: peer closed"}) == \
        "Ade OS unreachable: RemoteProtocolError: peer closed"
    assert error_cause({"error": "ConnectTimeout: timed out"}) == \
        "no answer in time: ConnectTimeout: timed out"


def test_task_types_from_the_400_envelope():
    result = {"error": {"code": "unknown_task_type", "message": "x",
                        "detail": {"task_types": ["coding", "qa"]}},
              "status": 400}
    assert task_types_from(result) == ["coding", "qa"]
    assert task_types_from({"error": "refused"}) == []


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
