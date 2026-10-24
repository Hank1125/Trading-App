"""Minimal, dependency-free MediaWiki template reader.

Only what the Siege parser needs: find `{{Name ...}}` occurrences (nested anywhere), and split
them into named/positional params while respecting nested `{{...}}` and `[[...]]`.
"""

import re
from dataclasses import dataclass, field

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_REF_BLOCK = re.compile(r"<ref\b[^>]*?(?<!/)>.*?</ref>", re.S | re.I)
_REF_SELF = re.compile(r"<ref\b[^>]*/>", re.I)


@dataclass(frozen=True)
class Template:
    name: str
    params: dict[str, str] = field(default_factory=dict)
    positional: tuple[str, ...] = ()
    offset: int = 0  # position in the cleaned source, for stable ordering

    def get(self, key: str, default: str = "") -> str:
        return self.params.get(key, default)


def clean(text: str) -> str:
    """Drop HTML comments and <ref> footnotes, which may contain stray `|`, `{{` or broken quotes."""
    text = _COMMENT.sub("", text)
    text = _REF_BLOCK.sub("", text)
    return _REF_SELF.sub("", text)


def _matching_close(text: str, start: int) -> int:
    """Index just past the `}}` closing the `{{` at `start`, or -1 if unbalanced."""
    depth = 0
    i = start
    n = len(text)
    while i < n - 1:
        pair = text[i : i + 2]
        if pair == "{{":
            depth += 1
            i += 2
        elif pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    return -1


def _split_top_level(body: str) -> list[str]:
    parts: list[str] = []
    depth_t = depth_l = 0
    buf_start = 0
    i = 0
    n = len(body)
    while i < n:
        pair = body[i : i + 2]
        if pair == "{{":
            depth_t += 1
            i += 2
            continue
        if pair == "}}" and depth_t:
            depth_t -= 1
            i += 2
            continue
        if pair == "[[":
            depth_l += 1
            i += 2
            continue
        if pair == "]]" and depth_l:
            depth_l -= 1
            i += 2
            continue
        if body[i] == "|" and depth_t == 0 and depth_l == 0:
            parts.append(body[buf_start:i])
            buf_start = i + 1
        i += 1
    parts.append(body[buf_start:])
    return parts


def _top_level_equals(part: str) -> int:
    depth = 0
    for i, ch in enumerate(part):
        if part.startswith(("{{", "[["), i):
            depth += 1
        elif part.startswith(("}}", "]]"), i) and depth:
            depth -= 1
        elif ch == "=" and depth == 0:
            return i
    return -1


def parse_template(src: str, offset: int = 0) -> Template:
    """Parse one `{{Name|a=b|c}}` string (including the outer braces)."""
    parts = _split_top_level(src[2:-2])
    name = parts[0].strip()
    params: dict[str, str] = {}
    positional: list[str] = []
    for part in parts[1:]:
        eq = _top_level_equals(part)
        if eq == -1:
            positional.append(part.strip())
        else:
            params[part[:eq].strip()] = part[eq + 1 :].strip()
    return Template(name=name, params=params, positional=tuple(positional), offset=offset)


def find_templates(text: str, name: str) -> list[Template]:
    """Every `{{name ...}}` in already-cleaned text, at any nesting depth, in source order.

    Matching is exact on the template name, so `Match` does not match `Matchlist`.
    """
    pattern = re.compile(r"\{\{\s*" + re.escape(name) + r"\s*(?=[|}])")
    found: list[Template] = []
    for m in pattern.finditer(text):
        end = _matching_close(text, m.start())
        if end != -1:
            found.append(parse_template(text[m.start() : end], offset=m.start()))
    return found


def first_template(value: str, name: str) -> Template | None:
    found = find_templates(value, name)
    return found[0] if found else None
