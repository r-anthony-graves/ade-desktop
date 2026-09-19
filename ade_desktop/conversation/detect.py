"""The chat's bare-line detector: a line-for-line port of
adeos/avatar/terminal-detect.js (see its header, and the 2026-09-13
chat-terminal-commands spec for the full rule set and its trade-offs).

Conservative to chat by design: only lines that clearly look like commands
are commands; everything else stays Ade's. Fixed sets and hard syntax, never
free parsing. Pure.
"""

from __future__ import annotations

import re

# Step 1: conversational openers head to chat BEFORE any syntax rule -- "hi;
# how are you" is a message with a semicolon, not a background job.
STOP = frozenset((
    "hi hey hello good morning good afternoon good evening nice thanks thank "
    "you please what why how who when where maybe sure ok okay yes no is are "
    "am was were will can could should would did does do have has had i you "
    "we they he she it").split())

# Step 3: cmdlet families. The dash is load-bearing: `get-process` matches,
# a bare `get` / `set` / `new` does not (those are prose).
FAMILY = re.compile(
    r"^(?:get|set|new|remove|copy|move|start|stop|restart|invoke|test|format|"
    r"select|where|out|read|write|export|import|convert|sort|measure|foreach|"
    r"add|clear|enable|disable|find|group|join|split|compare|resolve|push|pop|"
    r"show|open|close|enter|wait|receive|trace|debug)-", re.I)

# Step 4a: unambiguous aliases -- deliberately tight (no copy/move/select/
# echo/start/where/help/man/clear: prose words that share a command's name).
ALIAS = frozenset(("ls dir cat type cd pwd cls clr mv rm del md mkdir rd rmdir "
                   "gc gci gi ri sl set-location psh").split())

# Step 4b: the CLIs that live on this machine. Exact first token.
CLI = frozenset(("git npm npx node python py pip pip3 cargo docker kubectl rg "
                 "curl wget winget choco ssh scp taskkill tasklist netstat "
                 "ipconfig tracert whoami hostname ver systeminfo").split())

RE_FLAG = re.compile(r"(?:^|\s)-{1,2}[A-Za-z0-9]")
RE_ANGLE = re.compile(r"[<>]")
RE_PIPE = re.compile(r"\|")
RE_SEMI = re.compile(r";")
RE_STAR = re.compile(r"\*")
RE_ASSIGN = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\s*=")
RE_CALLOP = re.compile(r"^&\s")
RE_OPEN = re.compile(r"^[(\[]")
RE_EXT = re.compile(r"\.(?:ps1|bat|cmd|exe|jar|py|js)$", re.I)
_SYNTAX = (RE_FLAG, RE_ANGLE, RE_PIPE, RE_SEMI, RE_STAR, RE_ASSIGN,
           RE_CALLOP, RE_OPEN)

# PowerShell's quotes include the typographic ones a word processor types.
_SINGLE = frozenset("'" + chr(0x2018) + chr(0x2019) + chr(0x201A) + chr(0x201B))
_DOUBLE = frozenset('"' + chr(0x201C) + chr(0x201D) + chr(0x201E))
_ESCAPE = chr(96)       # the backtick: escapes the next character outside '...'


def _unbalanced_quotes(line: str) -> bool:
    """Would PowerShell reject this line as an unterminated string? A ''
    inside single quotes is an escaped quote (it toggles twice); a
    backtick escapes the next character everywhere but in single quotes."""
    single = double = False
    i = 0
    while i < len(line):
        c = line[i]
        if c == _ESCAPE and not single:
            i += 2
            continue
        if c in _SINGLE and not double:
            single = not single
        elif c in _DOUBLE and not single:
            double = not double
        i += 1
    return single or double


def detect(raw) -> tuple[bool, str]:
    """(is_command, reason); reason is one of empty, multiline, unbalanced,
    conversation, syntax, cmdlet, name, path, prose."""
    v = str("" if raw is None else raw).strip()
    if not v:
        return (False, "empty")
    # Step 0 (desktop, 2026-09-18; the avatar has neither): what no bare
    # command can be. Ray pasted a multi-line prompt beginning "-Analyze
    # ADE OS's ..." with **bold** in it: step 2 saw a flag and a wildcard
    # across the WHOLE paste, and it ran as PowerShell, ungated. A command
    # is one line (! runs anything else), and an unterminated quote is a
    # line PowerShell could not even parse -- so both are Ade's.
    if "\n" in v or "\r" in v:
        return (False, "multiline")
    if _unbalanced_quotes(v):
        return (False, "unbalanced")
    tok = v.split()[0].lower()
    # Step 1: compare the token with trailing punctuation stripped ("hi;"
    # must find "hi"). Everything after keeps the RAW token.
    if re.sub(r"[^a-z0-9-]+$", "", tok) in STOP:
        return (False, "conversation")
    # Step 2: hard syntax a bare command line cannot be missing.
    if any(rx.search(v) for rx in _SYNTAX):
        return (True, "syntax")
    # Step 3: cmdlet families (dash required).
    if FAMILY.search(tok):
        return (True, "cmdlet")
    # Step 4: exact-token alias / CLI names.
    if tok in ALIAS or tok in CLI:
        return (True, "name")
    # Step 5: program / path shapes.
    if "\\" in v or "/" in v or RE_EXT.search(tok) or re.fullmatch(r"\.{1,2}", tok):
        return (True, "path")
    # Step 6: everything else is Ade's.
    return (False, "prose")
