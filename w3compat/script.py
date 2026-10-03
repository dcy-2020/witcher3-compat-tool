"""Token-aware, function-scoped renaming of two known reserved identifiers.

This is a conservative recognizer, not a full WitcherScript parser. Unknown or
ambiguous constructs become diagnostics, never a global search-and-replace.
"""
from dataclasses import dataclass
import bisect
import re

RESERVED = {"set": "w3compatSet", "map": "w3compatMap"}
IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


class ScriptError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    value: str
    start: int
    end: int
    kind: str


def decode(data):
    """Only unambiguous UTF encodings are writable; never guess a code page."""
    for bom, encoding in ((b"\xff\xfe", "utf-16-le"),
                          (b"\xfe\xff", "utf-16-be"),
                          (b"\xef\xbb\xbf", "utf-8")):
        if data.startswith(bom):
            return data[len(bom):].decode(encoding), encoding, bom
    if b"\x00" in data:
        raise ScriptError("NUL bytes without a UTF BOM; encoding is ambiguous")
    return data.decode("utf-8"), "utf-8", b""


def tokenize(source):
    tokens, i = [], 0
    while i < len(source):
        char = source[i]
        if char.isspace():
            i += 1
        elif source.startswith("//", i):
            end = source.find("\n", i + 2)
            i = len(source) if end < 0 else end + 1
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise ScriptError("Unterminated block comment")
            i = end + 2
        elif char in "\"'":
            start, quote = i, char
            i += 1
            while i < len(source) and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
            if i >= len(source):
                raise ScriptError("Unterminated string or name literal")
            i += 1
            tokens.append(Token(source[start:i], start, i, "literal"))
        else:
            match = IDENT.match(source, i)
            if match:
                tokens.append(Token(match.group(), i, match.end(), "ident"))
                i = match.end()
            else:
                tokens.append(Token(char, i, i + 1, "symbol"))
                i += 1
    return tokens


def pair_delimiters(tokens):
    pairs, stack = {}, []
    closing = {")": "(", "}": "{", "]": "["}
    for i, token in enumerate(tokens):
        value = token.value
        if token.kind == "literal":
            continue
        if value in ("(", "{", "["):
            stack.append((value, i))
        elif value in closing:
            if not stack or stack[-1][0] != closing[value]:
                raise ScriptError("Unbalanced delimiters")
            _, start = stack.pop()
            pairs[start] = i
            pairs[i] = start
    if stack:
        raise ScriptError("Unbalanced delimiters")
    return pairs


def _parameter_groups(tokens, start, end):
    groups, left, depth = [], start, 0
    for i in range(start, end):
        value = tokens[i].value
        if value in ("<", "(", "["):
            depth += 1
        elif value in (">", ")", "]"):
            depth -= 1
        elif value == "," and depth == 0:
            groups.append(list(range(left, i)))
            left = i + 1
    groups.append(list(range(left, end)))
    return groups


def analyze(data):
    """Return new bytes, edit positions and warnings; never alter fields/types."""
    source, encoding, bom = decode(data)
    if re.search(r"(?m)^\s*(?:<<<<<<<|=======|>>>>>>>|\|\|\|\|\|\|\|)", source):
        raise ScriptError("Unresolved merge markers")
    tokens = tokenize(source)
    pairs = pair_delimiters(tokens)
    newline_positions = [-1] + [m.start() for m in re.finditer("\n", source)]
    line_at = lambda offset: bisect.bisect_left(newline_positions, offset)
    warnings, edits, functions, covered = [], [], [], set()

    for i, token in enumerate(tokens):
        if token.value != "function" or token.kind != "ident":
            continue
        name_i = i + 1
        if name_i + 1 < len(tokens) and tokens[name_i].value in ("get", "set") and tokens[name_i + 1].kind == "ident":
            name_i += 1  # Accessor prefix is not an identifier declaration.
        if name_i + 1 >= len(tokens) or tokens[name_i].kind != "ident" or tokens[name_i + 1].value != "(":
            raise ScriptError("Unsupported function declaration")
        open_i, close_i = name_i + 1, pairs[name_i + 1]
        stop = close_i + 1
        while stop < len(tokens) and tokens[stop].value not in ("{", ";"):
            stop += 1
        if stop == len(tokens):
            raise ScriptError("Function has no body or terminating semicolon")
        end = pairs[stop] if tokens[stop].value == "{" else stop
        functions.append((i, name_i, open_i, close_i, stop, end))

    for i, name_i, open_i, close_i, body_i, end in functions:
        function = tokens[name_i].value
        declaration_indices = []
        declarations = []
        unsafe = None
        for group in _parameter_groups(tokens, open_i + 1, close_i):
            if not group:
                continue
            colons = [j for j in group if tokens[j].value == ":"]
            if not colons:
                unsafe = "Unsupported parameter declaration"
                continue
            colon = colons[0]
            prefix = [tokens[j].value for j in group if j < colon]
            if not prefix or prefix[-1] in ("optional", "out") or any(v not in ("optional", "out") for v in prefix[:-1]) or tokens[colon - 1].kind != "ident":
                unsafe = "Unsupported parameter declaration"
                continue
            declaration_indices.append(colon - 1)
            declarations.append(tokens[colon - 1].value)

        if tokens[body_i].value == "{":
            for j in range(body_i + 1, end):
                if tokens[j].value != "var":
                    continue
                colon = j + 1
                while colon < end and tokens[colon].value not in (":", ";", "{", "}"):
                    colon += 1
                if colon == end or tokens[colon].value != ":":
                    unsafe = "Unsupported local declaration"
                    continue
                names = list(range(j + 1, colon))
                if not names or any(tokens[k].kind != "ident" if (k - j) % 2 else tokens[k].value != "," for k in names) or len(names) % 2 == 0:
                    unsafe = "Unsupported local declaration"
                    continue
                declaration_indices.extend(names[::2])
                declarations.extend(tokens[k].value for k in names[::2])

        for old, new in RESERVED.items():
            occurrences = [j for j in range(open_i + 1, end + 1) if tokens[j].kind == "ident" and tokens[j].value == old]
            if old not in declarations:
                continue
            covered.update(occurrences)
            reason = unsafe
            if declarations.count(old) != 1:
                reason = "Duplicate declarations or shadowing"
            if any(t.kind == "ident" and t.value.casefold() == new.casefold() for t in tokens):
                reason = "Replacement identifier already exists in this file"
            if any(start > i and start < end for start, *_ in functions):
                reason = "Nested functions are unsupported"
            if any(tokens[j].value == old and tokens[j].kind == "ident" and tokens[j + 1].value == ":" and j not in declaration_indices for j in range(open_i + 1, end)):
                reason = "Ambiguous label or named argument"
            # A collection type with the same spelling inside this scope is
            # valid 5.x syntax, but mixing type/value spellings is not repaired.
            if any(j not in declaration_indices and j + 1 < len(tokens) and tokens[j + 1].value == "<" and j > 0 and tokens[j - 1].value in (":", "<", ",") for j in occurrences):
                reason = "Collection type and variable share a spelling"
            if reason:
                warnings.append(dict(code="reserved_identifier_manual", line=line_at(tokens[i].start), function=function, identifier=old, reason=reason))
                continue
            for j in occurrences:
                if j > 0 and tokens[j - 1].value == ".":
                    continue  # Member names are not local references.
                t = tokens[j]
                edits.append(dict(start=t.start, end=t.end, old=old, new=new,
                                  function=function, line=line_at(t.start)))

    for j, token in enumerate(tokens):
        if token.kind != "ident" or token.value not in RESERVED or j in covered:
            continue
        previous = tokens[j - 1].value if j else ""
        following = tokens[j + 1].value if j + 1 < len(tokens) else ""
        accessor = previous == "function" and following not in ("(", ":")
        if following == ":" or (following == "(" and previous == "function"):
            warnings.append(dict(code="reserved_identifier_manual", line=line_at(token.start), identifier=token.value, reason="Field, function or unsupported declaration; cross-file semantics require review"))
        elif following != "<" and not accessor and previous != ".":
            warnings.append(dict(code="reserved_token_review", line=line_at(token.start), identifier=token.value, reason="Unresolved token outside a safely recognized local scope"))

    # A manual warning anywhere prevents partial repairs to this file.
    if warnings:
        edits = []
    unique = {edit["start"]: edit for edit in edits}
    edits = sorted(unique.values(), key=lambda e: e["start"])
    result = source
    for edit in reversed(edits):
        result = result[:edit["start"]] + edit["new"] + result[edit["end"]:]
    return bom + result.encode(encoding), edits, warnings
