"""Redaction shared by API responses, streamed text, and persisted traces."""

import json
import re
from collections.abc import Iterator
from typing import Any

_EMAIL = re.compile(
    r"(?<![\w.+%-])[A-Za-z0-9._%+-]{1,64}@"
    r"(?=[A-Za-z0-9.-]{1,253}(?![A-Za-z0-9.-]))"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}"
    r"(?![\w-])"
)
_SSN = re.compile(r"(?<!\w)[0-9]{3}-[0-9]{2}-[0-9]{4}(?!\w)")
_CARD = re.compile(
    r"(?<![\w+-])(?:[0-9]{13,19}|[0-9]{4}[ -][0-9]{6}[ -][0-9]{5}|"
    r"[0-9]{4}(?:[ -][0-9]{4}){2}(?:[ -][0-9]{1,4}){1,2})(?!\w)"
)
_PHONE = re.compile(
    r"(?<![\w+])(?:\+1[ .-]?(?:\([2-9][0-9]{2}\)|[2-9][0-9]{2})[ .-]?[2-9][0-9]{2}[ .-]?[0-9]{4}|"
    r"(?:1[ .-]?)?(?:\([2-9][0-9]{2}\)|[2-9][0-9]{2})[ .-]?[2-9][0-9]{2}[ .-]?[0-9]{4}|"
    r"\+[1-9](?:[ .-]?[0-9]){7,14})(?!\w)"
)
_IDENTIFIER_LABEL = re.compile(
    r"\b(?:isbn(?:-1[03])?|(?:order|invoice|tracking|reference|ticket|booking)"
    r"(?:[ \t]+(?:id|number|no\.?))?)[ \t:#=-]*$",
    re.IGNORECASE,
)
_PATTERNS = (("EMAIL", _EMAIL), ("SSN", _SSN), ("CREDIT_CARD", _CARD), ("PHONE", _PHONE))

# The longest supported token is an email with a 64-character local part and
# 253-character domain. Retain one extra character for the right boundary.
_STREAM_LOOKAHEAD = 320
_LABEL_LOOKBEHIND = 64
_PII_NUMBER_FIELDS = {
    "phone": "PHONE",
    "phonenumber": "PHONE",
    "telephone": "PHONE",
    "ssn": "SSN",
    "socialsecuritynumber": "SSN",
    "cardnumber": "CREDIT_CARD",
    "creditcardnumber": "CREDIT_CARD",
}


def _luhn_valid(value: str) -> bool:
    digits = [int(c) for c in value if "0" <= c <= "9"]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    for i, digit in enumerate(reversed(digits)):
        doubled = digit * 2 if i % 2 else digit
        total += doubled - 9 if doubled > 9 else doubled
    return total % 10 == 0


def _is_pii(kind: str, text: str, match: re.Match) -> bool:
    value = match.group()
    if kind == "EMAIL":
        return True
    if _IDENTIFIER_LABEL.search(text[max(0, match.start() - _LABEL_LOOKBEHIND) : match.start()]):
        return False
    if kind == "CREDIT_CARD":
        digits = re.sub(r"[ -]", "", value)
        if len(digits) == 13 and digits.startswith(("978", "979")):
            return False
        return _luhn_valid(digits)
    if kind == "SSN":
        area, group, serial = value.split("-")
        return area not in {"000", "666"} and area < "900" and group != "00" and serial != "0000"
    return True


def _matches(text: str, patterns=_PATTERNS) -> Iterator[tuple[int, int, str]]:
    matches = sorted(
        (match.start(), priority, match.end(), kind)
        for priority, (kind, pattern) in enumerate(patterns)
        for match in pattern.finditer(text)
        if _is_pii(kind, text, match)
    )
    end = 0
    for start, _, finish, kind in matches:
        if start >= end:
            yield start, finish, f"[REDACTED_{kind}]"
            end = finish


def _mask_prefix(text: str, start: int, limit: int, patterns=_PATTERNS) -> tuple[str, int]:
    parts = []
    cursor = start
    for left, right, replacement in _matches(text, patterns):
        if left < start:
            continue
        if left >= limit:
            break
        if right > limit:
            limit = left
            break
        parts.extend((text[cursor:left], replacement))
        cursor = right
    parts.append(text[cursor:limit])
    return "".join(parts), limit


def redact_text(text: str) -> str:
    return _mask_prefix(text, 0, len(text))[0]


def _redact_credit_cards(text: str) -> str:
    return _mask_prefix(text, 0, len(text), (("CREDIT_CARD", _CARD),))[0]


def redact_pii(value: Any) -> Any:
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                structured = json.loads(value)
            except ValueError:
                pass
            else:
                if isinstance(structured, (dict, list)):
                    masked = redact_pii(structured)
                    return json.dumps(masked, ensure_ascii=False) if masked != structured else value
        return redact_text(value)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            field = re.sub(r"[^a-z]", "", str(key).lower())
            kind = _PII_NUMBER_FIELDS.get(field)
            # Choice logprobs can expose the original text through tokens and byte arrays.
            if key == "logprobs" and ("message" in value or "delta" in value):
                result[key] = None
            elif kind and type(item) is int:
                result[key] = f"[REDACTED_{kind}]"
            else:
                result[key] = redact_pii(item)
        return result
    if isinstance(value, list):
        return [redact_pii(item) for item in value]
    return value


class StreamRedactor:
    def __init__(self) -> None:
        self._history = ""
        self._pending = ""

    def feed(self, text: str, *, final: bool = False) -> str:
        combined = self._history + self._pending + text
        start = len(self._history)
        limit = (
            len(combined)
            if final
            else max(start, combined.rfind("\n") + 1, len(combined) - _STREAM_LOOKAHEAD)
        )
        masked, consumed = _mask_prefix(combined, start, limit)
        self._history = combined[max(0, consumed - _LABEL_LOOKBEHIND) : consumed]
        self._pending = combined[consumed:]
        return masked


class JsonStreamRedactor:
    """Release a complete JSON value so structural redaction preserves valid JSON."""

    def __init__(self) -> None:
        self._parts: list[str] = []

    def feed(self, text: str, *, final: bool = False) -> str:
        self._parts.append(text)
        return redact_pii("".join(self._parts)) if final else ""
