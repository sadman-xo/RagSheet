"""Input guard: length limit and injection flags.

Injection patterns set an audit flag. Security never depends on them: the plan is checked in code and the
tools run on the user's own scope file. A strong pattern (instruction override, role play, SQL, markup) also keeps
the turn away from the LLM: rules and template answers only (blocks_llm). The soft pattern "show all regions" is
a normal question for an all-data role, so it only sets the flag.
"""

from __future__ import annotations

import re

MAX_CHARS = 500

INJECTION_PATTERNS = [
    r"ignore (all |the |any )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (the |all )?(rules|instructions|system)",
    r"(you are|act as|pretend to be) (now )?(an? )?(admin|administrator|root|developer|dan)\b",
    r"system prompt",
    r"jailbreak",
    r"bypass (the )?(security|filter|rules|scope)",
    r"(show|give|reveal).{0,30}(all|every|other) (regions?|categories|customers|users|data)",
    r"\b(drop|delete|truncate|update|insert)\s+(table|from|into)\b",
    r";\s*select\b|union\s+select",
    r"<\s*/?\s*(script|system|im_start|im_end)",
    r"\bset_config\b|\bapp\.user_id\b",
]
_RE = [re.compile(p, re.I) for p in INJECTION_PATTERNS]
SOFT_PATTERNS = {6}  # "show all regions ...": a flag only


class GuardError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def check(message: str) -> tuple[str, list[str]]:
    text = (message or "").strip()
    if not text:
        raise GuardError(422, "EMPTY", "Please type a question.")
    if len(text) > MAX_CHARS:
        raise GuardError(422, "TOO_LONG", f"Questions can have at most {MAX_CHARS} characters.")
    flags = [f"injection:{i}" for i, r in enumerate(_RE) if r.search(text)]
    return text, (["injection"] + flags) if flags else []


def blocks_llm(flags: list[str]) -> bool:
    """True if a strong injection pattern matched: the turn uses rules and templates only."""
    return any(f.startswith("injection:") and int(f.split(":")[1]) not in SOFT_PATTERNS for f in flags)
