"""Context for a narrated answer (about 1,800 tokens).

Order: static system block (prefix reuse), scope line, [R#] results, metric definitions, [S#] snippets, notices,
the question. A size guard removes [S#] snippets first and history second; it never removes the system block.
"""

from __future__ import annotations

from app.analytics import formatting
from app.analytics.metrics import METRICS
from app.chat import prompts
from app.chat.templates import DIM_LABEL, _filters_text
from app.security.policy import Scope

MAX_PROMPT_TOKENS = 3000
MAX_ROWS_IN_PROMPT = 12


def _tokens(text: str) -> int:
    return len(text) // 4 + 1


def result_text(r: dict) -> str:
    if r["kind"] != "table":
        return ""
    dims = [c["key"] for c in r["columns"] if c["role"] == "dim"]
    metrics = [c["key"] for c in r["columns"] if c["role"] == "metric"]
    head = f"[{r['ref']}] {r['title']}: " + ", ".join(METRICS[m].label for m in metrics)
    if dims:
        head += " by " + ", ".join(DIM_LABEL.get(d, d) for d in dims)
    head += _filters_text(r.get("spec"))
    if r.get("compare"):
        head += f" (compared with: {r['compare']})"
    lines = [head]

    def fmt(row: dict) -> str:
        parts = []
        for m in metrics:
            s = f"{METRICS[m].label} {formatting.metric_value(m, row.get(m))}"
            if row.get(f"{m}__prior") is not None:
                s += f" (prior {formatting.metric_value(m, row.get(m + '__prior'))}, change {formatting.delta_text(m, row.get(m), row.get(m + '__prior'))})"
            n = row.get(f"{m}__n")
            if n is not None and n < 30:
                s += " (fewer than 30 orders)"
            parts.append(s)
        return "; ".join(parts)

    for row in r["rows"][:MAX_ROWS_IN_PROMPT]:
        label = " / ".join(str(row[d]) for d in dims)
        lines.append(f"- {label}: {fmt(row)}")
    if r.get("row_count", 0) > MAX_ROWS_IN_PROMPT:
        lines.append(f"- ({r['row_count'] - MAX_ROWS_IN_PROMPT} more rows not shown)")
    if r.get("totals") and (dims or not r["rows"]):
        lines.append(f"- Total: {fmt(r['totals'])}")
    elif not dims and r["rows"]:
        lines[-1] = f"- Value: {fmt(r['rows'][0])}" if len(lines) > 1 else lines[-1]
    return "\n".join(lines)


def build(question: str, scope: Scope, results: list[dict], snippets: list[dict], notices: list[str],
          history: list[str] | None = None) -> list[dict]:
    used = []
    for r in results:
        for c in r.get("columns", []):
            if c["role"] == "metric" and c["key"] not in used:
                used.append(c["key"])
    defs = "\n".join(f"- {METRICS[m].label}: {METRICS[m].description}" for m in used)
    res_text = "\n".join(t for t in (result_text(r) for r in results) if t)
    snips = list(snippets)
    hist = list(history or [])

    def render() -> str:
        parts = [f"SCOPE: {prompts.scope_line(scope)}"]
        if res_text:
            parts.append("RESULTS:\n" + res_text)
        if defs:
            parts.append("DEFINITIONS:\n" + defs)
        if snips:
            parts.append("SNIPPETS:\n" + "\n".join(f"[{s['ref']}] {s['title']}: {s['text']}" for s in snips))
        if notices:
            parts.append("NOTICES:\n" + "\n".join(f"- {n}" for n in notices))
        if hist:
            parts.append("EARLIER QUESTIONS: " + " | ".join(hist[-3:]))
        parts.append(f"QUESTION: {question}")
        return "\n\n".join(parts)

    text = render()
    while _tokens(prompts.ANSWER_SYSTEM) + _tokens(text) > MAX_PROMPT_TOKENS and (snips or hist):
        if snips:
            snips.pop()
        elif hist:
            hist.pop(0)
        text = render()
    return [{"role": "system", "content": prompts.ANSWER_SYSTEM}, {"role": "user", "content": text}]


def kept_snippets(messages: list[dict]) -> set[str]:
    content = messages[-1]["content"]
    import re

    return set(re.findall(r"^\[(S\d+)\]", content, re.M))
