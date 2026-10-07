"""Shared helpers: canonical JSON, content hashing, Decimal parsing and formatting."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation, getcontext
from typing import Any

getcontext().prec = 28

GENERATOR_VERSION = "gen-0.2.0"
VERIFIER_VERSION = "ver-0.1.5"
ENV_VERSION = "env-0.2.1"

# Tolerance used by the verifier: |pred - ref| <= ATOL + RTOL * |ref|
# Lower bound: the protocol allows reporting 4 significant digits, which can be off by up to 0.05%.
# RTOL = 0.1% accepts that with 2x headroom.
RTOL = Decimal("1e-3")
ATOL = Decimal("1e-9")
# Upper bound: every known wrong path must miss the reference by at least this many tolerances (0.5%),
# so a wrong value rounded toward the reference (at most 0.05%) still fails.
DISCRIMINATIVE_MARGIN = Decimal(5)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def to_decimal(value: Any) -> Decimal:
    """Parse a number the way a strict grader would. Raises ValueError on anything non-numeric."""
    if isinstance(value, bool):
        raise ValueError("booleans are not numbers")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"not a number: {value!r}") from exc
        if not result.is_finite():
            raise ValueError(f"not a finite number: {value!r}")
        return result
    raise ValueError(f"unsupported numeric type: {type(value).__name__}")


def fmt_number(value: Decimal, style: str = "plain") -> str:
    """Six significant digits, either plain decimal or scientific notation."""
    if style == "sci":
        return format(value, ".5e")
    text = format(value, ".6g")
    if "e" in text or "E" in text:
        text = format(Decimal(text), "f")
    return text


def within_tolerance(pred: Decimal, ref: Decimal, margin: Decimal = Decimal(1)) -> bool:
    return abs(pred - ref) <= margin * (ATOL + RTOL * abs(ref))
