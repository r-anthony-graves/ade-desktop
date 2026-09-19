"""The bare-command detector, held to the avatar's own golden cases
(adeos/avatar/tests/chat-terminal.test.js, verbatim) so a line runs or
chats the same way in both apps."""

from ade_desktop.conversation.detect import detect

SHOULD_RUN = [
    'get-process', 'get-process -Name powershell', 'Set-Location D:\\temp',
    'ls', 'ls -la', 'dir', 'cd C:\\Users', 'pwd', 'cls', 'git status',
    "git commit -m 'release'", 'node --version', 'python -m http.server 8000',
    'npm run build', '.\\scripts\\adeos-run.ps1', '..', '.',
    'D:\\tradinglocal\\live.py', 'whoami', 'ipconfig /all',
    'C:\\Program Files\\Git\\bin\\git.exe --version', '$x = 42', 'dir | clip',
    'ping 1.1.1.1 > nul', '& cmd /c dir', '-List', 'get-childitem C:\\Users',
    '.\\activate.ps1',
]

SHOULD_CHAT = [
    'hi how are you', 'hi; how are you', 'hello, world', 'hello',
    'what is the weather', 'why does the build fail', 'please fix the bug',
    'set a reminder for tomorrow', 'the cat is on the roof',
    'list all files in the project', 'start the build',
    'get the latest commit message', 'new feature for coding agent',
    'remove everything from the disk', 'i think we should deploy', 'echo hello',
    'clear the screen', 'man git', 'thanks for all the help', 'gitlab is down',
    'where are my keys', 'show dirs in the project', 'copy that', 'move on',
    'select the option', 'can you list files',
]


def test_command_lines_are_commands():
    for line in SHOULD_RUN:
        assert detect(line)[0] is True, (line, detect(line))


def test_everything_else_stays_ades():
    for line in SHOULD_CHAT:
        assert detect(line)[0] is False, (line, detect(line))


def test_stop_wins():
    assert detect('hi; how are you') == (False, 'conversation')
    assert detect('please run git status')[0] is False


def test_first_token_is_case_insensitive():
    for line in ('Get-Process', 'GIT STATUS', 'LS', 'WHOAMI'):
        assert detect(line)[0] is True, line


def test_empty():
    for raw in ('', '   ', None):
        assert detect(raw) == (False, 'empty')


# -- prose that the syntax rules mistook for a command (Ray, 2026-09-18) -----------

BT = chr(96)          # PowerShell's escape character, the backtick
RSQ = chr(0x2019)     # a right single quotation mark: a word processor's apostrophe

RAY_PASTE = """-Analyze ADE OS's existing LLM and reasoning architecture and compare it with a tiered cognitive architecture:

1. **Fast LLM** - conversation, classification, routing, simple tasks.
2. **Reasoning layer** - planning, decomposition, diagnosis, tool selection."""


def test_a_pasted_multi_line_message_is_never_a_command():
    """The paste began with "-Analyze" (a flag, to step 2) and carried
    **bold** (a wildcard) -- and ran as PowerShell, ungated."""
    assert detect(RAY_PASTE) == (False, "multiline")
    assert detect("git status\ngit log") == (False, "multiline")   # ! is the way to run two
    assert detect("git status\n")[0] is True                        # a trailing newline is one line


def test_an_unbalanced_quote_is_prose_because_no_command_could_parse():
    assert detect("-Analyze ADE OS's existing LLM and reasoning architecture") == (
        False, "unbalanced")
    assert detect("-Explain Ade" + RSQ + "s reasoning layer") == (False, "unbalanced")
    assert detect('-Summarise the "architecture doc') == (False, "unbalanced")


def test_balanced_and_escaped_quotes_still_run():
    for line in ('git commit -m "Ray' + "'" + 's fix"',
                 "Write-Output 'it''s fine'",
                 'Write-Output "a ' + BT + '" b"',            # odd count, balanced only by the escape
                 "git commit -m 'release'"):
        assert detect(line)[0] is True, (line, detect(line))
