"""Shared safety-language policy for deterministic verification."""

from __future__ import annotations

import re

UNSAFE_ACTUATION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:execute|executed|deploy|deployed|apply|applied|push|pushed)\b.{0,60}\b(?:change|command|configuration|parameter|network)\b",
        r"\b(?:bypass|override|disable)\b.{0,40}\bguardrail",
        r"\b(?:approve|authorize)\b.{0,40}\b(?:network|configuration|parameter) change\b",
        r"\bnetwork change (?:is|was|has been) (?:approved|performed|completed)\b",
        r"\bsend (?:this |the )?(?:command|configuration)\b",
    )
)

UNSUPPORTED_OBSERVATION_PATTERNS = {
    "alarm": re.compile(
        r"(?:\b(?:observed|confirmed|shows?|indicates?)\b.{0,50}\balarm\b|"
        r"\balarm\b.{0,50}\b(?:confirms?|shows?|indicates?)\b)",
        re.I,
    ),
    "packet capture": re.compile(
        r"\bpacket (?:capture|trace)\b.{0,40}\b(?:shows?|confirms?|observed)\b", re.I
    ),
    "UE trace": re.compile(r"\bUE (?:trace|log)\b.{0,40}\b(?:shows?|confirms?|observed)\b", re.I),
    "drive test": re.compile(r"\bdrive test\b.{0,40}\b(?:shows?|confirms?|observed)\b", re.I),
    "node log": re.compile(
        r"\b(?:node|vendor) log\b.{0,40}\b(?:shows?|confirms?|observed)\b", re.I
    ),
}


def unsafe_actuation_claims(texts: list[str]) -> list[str]:
    return sorted(
        {
            text
            for text in texts
            if any(pattern.search(text) for pattern in UNSAFE_ACTUATION_PATTERNS)
        }
    )


def unsupported_observation_claims(texts: list[str]) -> list[str]:
    claims: list[str] = []
    for text in texts:
        for data_type, pattern in UNSUPPORTED_OBSERVATION_PATTERNS.items():
            if pattern.search(text):
                claims.append(f"unsupported observed data type {data_type!r}: {text}")
    return sorted(set(claims))
