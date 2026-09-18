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
