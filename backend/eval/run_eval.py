"""Run the gold evaluation set against a running Panorama (through the load balancer) and check the gates.

Usage (in the tests container, see scripts/run_eval.ps1):
    python -m eval.run_eval --base http://frontend --label qwen3-8b
    python -m eval.run_eval --numeric-only --csv /datasets/generated_1000000.csv --label 1m
It does not import application code: the expected numbers come from eval/reference.py.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

from eval import reference

ROOT = Path(__file__).resolve().parent
PASSWORD = "Demo@2024"
ORIGIN = "http://localhost:8080"
SCOPE = {"admin": "all:full", "exec": "all:full", "analyst": "all:pseudo", "ops": "all:nofin",
         "rm.namerica": "region:North America", "rm.europe": "region:Europe", "rm.asia": "region:Asia",
         "rm.mideast": "region:Middle East", "cm.electronics": "category:Electronics", "cm.clothing": "category:Clothing",
         "cm.home": "category:Home & Kitchen", "cm.books": "category:Books & Media", "cm.beauty": "category:Beauty & Health"}
KIND = {"gross_revenue": "money", "net_revenue": "money", "delivered_revenue": "money", "gross_profit": "money",
        "margin_pct": "pct", "return_rate": "pct", "cancellation_rate": "pct", "aov": "money", "unique_customers": "count",
        "repeat_customer_rate": "pct", "avg_shipping_days": "days", "open_orders": "count", "orders": "count"}
TARGETS = {  # seconds (planned for qwen3:8b x 1; the default is now 4B x 4; sample dataset, single user, warm model)
    "template_p95": 0.3, "narrate_rule_p50": 15, "narrate_rule_p95": 20, "narrate_planner_p50": 22, "narrate_planner_p95": 30,
}


def forms(v: float, kind: str) -> list[str]:
    if kind == "money":
        return [f"{v:,.2f}", f"{v:,.0f}", f"{v / 1e6:.2f}M", f"{v / 1e3:.1f}K"]
    if kind == "pct":
        return [f"{v:.2f}%", f"{v:.1f}%", f"{v:.2f} %", f"{v:.1f} %"]
    if kind == "days":
        return [f"{v:.1f}", f"{v:.2f}"]
    return [f"{int(round(v)):,}", f"{int(round(v))}"]


def numbers_in(obj) -> list[float]:
    out: list[float] = []
    if isinstance(obj, dict):
        for v in obj.values():
            out += numbers_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out += numbers_in(v)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append(float(obj))
    return out


NUM_RE = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+]?\d+(?:\.\d+)?")


def answer_numbers(text: str) -> list[float]:
    """Numbers in an AI answer, without years, small counts, period labels, and citation tags."""
    text = re.sub(r"\[[RSN]\d+\]", " ", text)
    text = re.sub(r"\b\d{4}-(?:Q[1-4]|\d{2})\b", " ", text)
    out = []
    for m in NUM_RE.findall(text):
        v = float(m.replace(",", ""))
        if v.is_integer() and (1990 <= v <= 2100 or abs(v) <= 12):
            continue
        out.append(v)
    return out


def agrees(v: float, pool: list[float]) -> bool:
    return any(abs(v - n) <= 0.0051 or (n and abs(abs(v) - abs(n)) / abs(n) <= 0.005) for n in pool)


def forbidden(df, scope_key: str) -> list[str]:
    vals = []
    kind, _, value = scope_key.partition(":")
    if kind in ("region", "category"):
        col = "region" if kind == "region" else "category"
        vals.append(df.revenue.sum())
        for other, g in df.groupby(col):
            if other != value:
                vals.append(g.revenue.sum())
    if scope_key == "all:nofin":
        vals += [df.profit.sum(), df.cost.sum()]
    return [f"{round(float(v), 2):,.2f}" for v in vals]


class Client:
    def __init__(self, base: str):
        self.http = httpx.Client(base_url=base, timeout=httpx.Timeout(180, connect=5), headers={"Origin": ORIGIN})
        self.tokens: dict[str, str] = {}

    def token(self, user: str) -> str:
        if user not in self.tokens:
            r = self.http.post("/api/auth/login", json={"username": user, "password": PASSWORD, "want_token": True})
            r.raise_for_status()
            self.tokens[user] = r.json()["access_token"]
        return self.tokens[user]

    def ask(self, user: str, question: str, parent: int | None = None, session: int | None = None) -> tuple[int, dict, float]:
        body = {"message": question, "turn_id": str(uuid.uuid4()), "cache": False, "parent_message_id": parent, "session_id": session}
        headers = {"Authorization": f"Bearer {self.token(user)}"}  # the login is not part of the answer time
        for attempt in (1, 2):
            t0 = time.perf_counter()
            r = self.http.post("/api/chat/ask", json=body, headers=headers)
            dt = time.perf_counter() - t0
            if r.status_code in (409, 429) and attempt == 1:
                time.sleep(float(r.headers.get("Retry-After", "2")) + 0.5)
                body["turn_id"] = str(uuid.uuid4())
                continue
            return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}), dt
        return r.status_code, {}, dt

    def wait_ready(self, timeout_s: float) -> str:
        t0 = time.time()
        state = "?"
        while time.time() - t0 < timeout_s:
            try:
                st = self.http.get("/api/chat/status", headers={"Authorization": f"Bearer {self.token('exec')}"}).json()
                state = st.get("state", "?")
                if state == "ready":
                    return state
                print(f"waiting for the AI: {st.get('label')} {st.get('progress') or ''}", flush=True)
            except httpx.HTTPError as exc:
                print(f"waiting for the api: {exc}", flush=True)
            time.sleep(10)
        return state


def p(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]


def run(args) -> dict:
    df_all = reference.load(args.csv)
    data = yaml.safe_load((ROOT / "gold_questions.yaml").read_text(encoding="utf-8"))["items"]
    if args.numeric_only:
        data = [i for i in data if i.get("kind") == "template" and i.get("expect")][:10]
    if args.only:
        data = [i for i in data if i["id"] in args.only.split(",")]
    c = Client(args.base)
    status = "skipped" if args.numeric_only else c.wait_ready(args.wait)
    results = []
    turn_ids: dict[str, tuple[int | None, int | None]] = {}
    for item in data:
        user = item["user"]
        scope_df = reference.scope(df_all, SCOPE[user])
        parent, session = turn_ids.get(item.get("parent"), (None, None)) if item.get("parent") else (None, None)
        code, body, dt = c.ask(user, item["question"], parent, session)
        done = body.get("done") or {}
        turn_ids[item["id"]] = (done.get("question_id"), done.get("session_id"))
        answer = body.get("answer", "") or ""
        res_numbers = numbers_in(body.get("results", []))
        mode = body.get("mode")
        plan = body.get("plan") or {}
        r = {"id": item["id"], "user": user, "question": item["question"], "kind": item["kind"], "status": code, "mode": mode,
             "intent": plan.get("intent"), "plan_source": plan.get("source"), "seconds": round(dt, 2),
             "llm_calls": done.get("llm_calls"), "answer": answer[:600], "checks": []}
        for exp in item.get("expect", []):
            val = reference.query(scope_df, [exp["metric"]], None, exp.get("filters"))[()][exp["metric"]]
            kind = KIND.get(exp["metric"], "money")
            in_table = val is not None and any(abs(n - val) <= 0.006 or (val and abs(n - val) / abs(val) < 1e-6) for n in res_numbers)
            in_text = val is not None and any(f in answer for f in forms(val, kind))
            r["checks"].append({"metric": exp["metric"], "filters": exp.get("filters"), "expected": val,
                                "in_table": in_table, "in_text": in_text})
        for t in item.get("text", []):
            r["checks"].append({"text": t, "ok": t.lower() in answer.lower() or t.lower() in " ".join(body.get("notices", [])).lower()})
        if item.get("intent"):
            want = item["intent"] if isinstance(item["intent"], list) else [item["intent"]]
            r["intent_ok"] = plan.get("intent") in want
        blob = json.dumps(body)
        leak_hits = [f for f in forbidden(df_all, SCOPE[user]) if f in blob]
        if item.get("forbid_raw_ids") or SCOPE[user] == "all:pseudo":
            if re.search(r"CUST-\d{5}", blob.replace("CUST-02791", "")):
                leak_hits.append("raw customer ID")
        r["leaks"] = leak_hits
        if item["kind"] == "narrate" and mode in ("ai", "ai_replaced"):
            nums = answer_numbers(answer)
            # the context of the answer: result tables (numbers and labels such as "40%") and the cited snippets
            pool = res_numbers + answer_numbers(json.dumps(body.get("results", []))) + \
                answer_numbers(" ".join(s.get("text", "") for s in body.get("sources", [])))
            r["answer_numbers"] = {"total": len(nums), "agree": sum(1 for v in nums if agrees(v, pool))}
        if item["kind"] == "refusal":
            r["refusal_ok"] = mode == "refusal" and (done.get("llm_calls") or 0) == 0
        print(f"{item['id']:4} {user:15} {mode or code!s:12} {dt:6.2f}s intent={plan.get('intent')} "
              f"{'LEAK ' if leak_hits else ''}{answer[:90]!r}", flush=True)
        results.append(r)
    return summarize(results, args, status)


def summarize(results: list[dict], args, status: str) -> dict:
    table_checks = [ch for r in results for ch in r["checks"] if "in_table" in ch]
    ans_total = sum(r.get("answer_numbers", {}).get("total", 0) for r in results)
    ans_agree = sum(r.get("answer_numbers", {}).get("agree", 0) for r in results)
    ans_ratio = (ans_agree / ans_total) if ans_total else 1.0
    text_items = [ch for r in results for ch in r["checks"] if "text" in ch]
    narrate = [r for r in results if r["kind"] == "narrate"]
    intents = [r for r in results if "intent_ok" in r]
    refusals = [r for r in results if r["kind"] == "refusal"]
    leaks = sum(len(r["leaks"]) for r in results)
    lat = {
        "template": [r["seconds"] for r in results if r["mode"] in ("template", "refusal")],
        "narrate_rule": [r["seconds"] for r in narrate if r["mode"] in ("ai", "ai_replaced") and r.get("plan_source") != "llm"],
        "narrate_planner": [r["seconds"] for r in narrate if r["mode"] in ("ai", "ai_replaced") and r.get("plan_source") == "llm"],
    }
    ratio = lambda xs: (sum(1 for x in xs if x) / len(xs)) if xs else 1.0  # noqa: E731
    gates = {
        "leaks": {"value": leaks, "pass": leaks == 0},
        "result_table_numbers": {"value": ratio([c["in_table"] for c in table_checks]), "pass": ratio([c["in_table"] for c in table_checks]) >= 0.98},
        "text_checks": {"value": ratio([c["ok"] for c in text_items]), "pass": ratio([c["ok"] for c in text_items]) >= 0.9},
        "intent_accuracy": {"value": ratio([r["intent_ok"] for r in intents]), "pass": ratio([r["intent_ok"] for r in intents]) >= 0.9},
        "refusal_recall": {"value": ratio([r["refusal_ok"] for r in refusals]), "pass": ratio([r["refusal_ok"] for r in refusals]) == 1.0},
    }
    if not args.numeric_only:
        narr_modes = [r["mode"] for r in narrate]
        ai_share = ratio([m in ("ai", "ai_replaced") for m in narr_modes])
        replaced = ratio([m == "ai_replaced" for m in narr_modes])
        gates.update({
            # share of the numbers in AI answers that agree with the result tables (0.5 % tolerance)
            "answer_text_numbers": {"value": ans_ratio, "pass": ans_ratio >= 0.9},
            "narrate_ai_modes": {"value": ai_share, "pass": ai_share == 1.0},
            "ai_replaced_share": {"value": replaced, "pass": replaced <= 0.10},
            "latency_template_p95_s": {"value": p(lat["template"], 0.95), "pass": (p(lat["template"], 0.95) or 0) <= TARGETS["template_p95"]},
            "latency_narrate_rule_p50_s": {"value": p(lat["narrate_rule"], 0.5), "pass": (p(lat["narrate_rule"], 0.5) or 0) <= TARGETS["narrate_rule_p50"]},
            "latency_narrate_rule_p95_s": {"value": p(lat["narrate_rule"], 0.95), "pass": (p(lat["narrate_rule"], 0.95) or 0) <= TARGETS["narrate_rule_p95"]},
        })
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "label": args.label, "model": args.label,
        "base": args.base, "ai_status": status, "items": len(results), "numeric_only": args.numeric_only,
        "gates": gates, "all_pass": all(g["pass"] for g in gates.values()),
        "summary": {"modes": {m: sum(1 for r in results if r["mode"] == m) for m in {r["mode"] for r in results}},
                    "latency_s": {k: {"p50": p(v, 0.5), "p95": p(v, 0.95), "n": len(v)} for k, v in lat.items()},
                    "planner_turns": sum(1 for r in results if r.get("plan_source") == "llm")},
        "results": results,
    }
    return report


def write(report: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"eval_{report['label']}_{stamp}"
    (out / f"{name}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if not report["numeric_only"]:
        (out / "latest.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = [f"# Panorama evaluation: {report['label']}", "", f"- Created: {report['created_at']}", f"- Items: {report['items']}",
             f"- All gates pass: **{report['all_pass']}**", "", "| Gate | Value | Pass |", "|---|---|---|"]
    for k, g in report["gates"].items():
        v = g["value"]
        lines.append(f"| {k} | {v:.3f} | {'yes' if g['pass'] else 'NO'} |" if isinstance(v, float) else f"| {k} | {v} | {'yes' if g['pass'] else 'NO'} |")
    lines += ["", "## Latency (seconds)", "", "| Path | p50 | p95 | n |", "|---|---|---|---|"]
    for k, v in report["summary"]["latency_s"].items():
        lines.append(f"| {k} | {v['p50']} | {v['p95']} | {v['n']} |")
    lines += ["", "## Items", "", "| id | user | mode | intent | s | checks |", "|---|---|---|---|---|---|"]
    for r in report["results"]:
        ok = all(c.get("in_table", c.get("ok", True)) for c in r["checks"]) and not r["leaks"]
        lines.append(f"| {r['id']} | {r['user']} | {r['mode']} | {r['intent']} | {r['seconds']} | {'ok' if ok else 'CHECK'} |")
    (out / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report: {out / name}.md", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://frontend")
    ap.add_argument("--csv", default=str(reference.default_csv()))
    ap.add_argument("--label", default="qwen3-8b")
    ap.add_argument("--out", default=str(ROOT / "reports"))
    ap.add_argument("--wait", type=float, default=1800)
    ap.add_argument("--numeric-only", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    report = run(args)
    write(report, Path(args.out))
    print(json.dumps(report["gates"], indent=2, default=str))
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
