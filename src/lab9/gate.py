"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]
    for name, rep in (("PR", pr), ("baseline", base)):
        problems += [f"{name}: {p}" for p in _report_problems(rep, graded, spec)]
    # Same (item, seed) set as the baseline: no cherry-picked seeds, no dropped or added items.
    pr_keys, base_keys = _keys(pr), _keys(base)
    if pr_keys != base_keys:
        missing, extra = sorted(base_keys - pr_keys), sorted(pr_keys - base_keys)
        problems.append(f"(item, seed) set differs from baseline: {len(missing)} missing "
                        f"{missing[:3]}, {len(extra)} extra {extra[:3]}")
    if sorted(pr["manifest"].get("seeds") or []) != sorted(base["manifest"].get("seeds") or []):
        problems.append(f"manifest seeds {pr['manifest'].get('seeds')} != baseline "
                        f"{base['manifest'].get('seeds')}")
    if pr["manifest"].get("items") != base["manifest"].get("items"):
        problems.append(f"manifest items {pr['manifest'].get('items')} != baseline {base['manifest'].get('items')}")
    # Slice tags come from the label; an item may not move out of (or into) a slice between runs.
    pr_sl, base_sl = _slice_tags(pr), _slice_tags(base)
    for item in sorted(set(pr_sl) & set(base_sl)):
        if pr_sl[item] != base_sl[item]:
            problems.append(f"{item}: slice tags {_fmt_tags(pr_sl[item])} != baseline {_fmt_tags(base_sl[item])}")
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _keys(rep: dict) -> set[tuple[str, int]]:
    return {(r.get("item_id"), r.get("seed")) for r in rep.get("rows") or []}


def _slice_tags(rep: dict) -> dict[str, frozenset | None]:
    """item -> its slice tags; None when the item's rows disagree with each other."""
    out: dict[str, frozenset | None] = {}
    for r in rep.get("rows") or []:
        tags = frozenset(r.get("slices") or [])
        item = r.get("item_id")
        out[item] = tags if out.get(item, tags) == tags else None
    return out


def _fmt_tags(tags: frozenset | None) -> str:
    return "inconsistent" if tags is None else str(sorted(tags))


def _bad_number(v) -> bool:
    return isinstance(v, float) and (math.isnan(v) or math.isinf(v))


def _report_problems(rep: dict, graded: list[str], spec: dict) -> list[str]:
    """Self-consistency of one report: it must be what lab9.eval wrote, untouched."""
    problems: list[str] = []
    rows = rep.get("rows") or []
    man = rep.get("manifest") or {}
    for k, v in (rep.get("metrics") or {}).items():
        if _bad_number(v):
            problems.append(f"metric {k} is {v}")
    if rep.get("evaluator_failures"):
        problems.append(f"{len(rep['evaluator_failures'])} evaluator failure(s), first: "
                        f"{str(rep['evaluator_failures'][0])[:80]}")
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows != {man.get('items')} items x {len(man.get('seeds') or [])} seeds")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1})
    if dups:
        problems.append(f"{len(dups)} duplicated (item, seed) row(s), first {dups[0]}")
    row_seeds = {r.get("seed") for r in rows}
    if rows and row_seeds != set(man.get("seeds") or []):
        problems.append(f"row seeds {sorted(row_seeds)} != manifest seeds {man.get('seeds')}")
    n_items = len({r.get("item_id") for r in rows})
    if rows and n_items != man.get("items"):
        problems.append(f"{n_items} distinct items in rows != manifest items {man.get('items')}")
    for m in graded:
        bad = [r for r in rows if not isinstance(r.get(m), bool)]
        if bad:
            problems.append(f"{len(bad)} row(s) with no valid {m} value (grader crashed or edited), "
                            f"first {bad[0].get('item_id')}@{bad[0].get('seed')}: {bad[0].get(m)!r}")
    # The metrics block must be what the rows say: recompute and compare.
    present = [m for m in graded if rows and all(isinstance(r.get(m), bool) for r in rows)]
    if present:
        has_cost = all("cost" in r for r in rows)
        rows_c = rows if has_cost else [{**r, "cost": 0.0} for r in rows]
        recomputed = aggregate(rows_c, present, k_values=spec.get("pass_k", []))
        if not has_cost:
            recomputed.pop("cost_per_success", None)
        for k, v in recomputed.items():
            if k not in (rep.get("metrics") or {}):
                continue
            got = rep["metrics"][k]
            if _bad_number(got):
                continue                                  # already reported above
            if (v is None) != (got is None) or (v is not None and abs(float(got) - float(v)) > 1e-6):
                problems.append(f"metric {k}={got} but rows give {v}")
    return problems


_LOOSER = {"max": lambda new, old: new > old, "max_increase": lambda new, old: new > old,
           "min": lambda new, old: new < old}


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => thresholds may only get stricter (a new version starts afresh)."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    problems: list[str] = []

    def compare(kind: str, key: str, new: dict | None, old: dict) -> None:
        if new is None:
            problems.append(f"RATCHET {kind} {key} removed")
            return
        if old.get("blocking") and not new.get("blocking"):
            problems.append(f"RATCHET {kind} {key} no longer blocking")
        if kind == "metric" and new.get("kind") != old.get("kind"):
            problems.append(f"RATCHET metric {key} kind {old.get('kind')} -> {new.get('kind')}")
        th_new = (new.get("threshold") or {}) if kind == "metric" else new
        th_old = (old.get("threshold") or {}) if kind == "metric" else old
        for bound, looser in _LOOSER.items():
            if bound in th_old:
                if bound not in th_new:
                    problems.append(f"RATCHET {kind} {key} dropped {bound}")
                elif looser(th_new[bound], th_old[bound]):
                    problems.append(f"RATCHET {kind} {key} {bound} {th_old[bound]} -> {th_new[bound]}")
        if th_old.get("no_significant_drop") and not th_new.get("no_significant_drop"):
            problems.append(f"RATCHET {kind} {key} dropped no_significant_drop")

    new_m = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        compare("metric", m["id"], new_m.get(m["id"]), m)
    # A slice is identified by (name, metric): changing its metric is removing it.
    new_s = {f"{sl['name']}/{sl['metric']}": sl for sl in spec.get("slices") or []}
    for sl in base_spec.get("slices") or []:
        key = f"{sl['name']}/{sl['metric']}"
        compare("slice", key, new_s.get(key), sl)
    # A wider CI (higher confidence, fewer resamples) or another rng is a looser "no significant drop".
    for key in ("seeds", "eval_set", "labels", "adversarial_pack", "bootstrap"):
        if base_spec.get(key) != spec.get(key):
            problems.append(f"RATCHET spec {key} changed: {base_spec.get(key)!r} -> {spec.get(key)!r}")
    if set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []):
        problems.append(f"RATCHET pass_k {base_spec.get('pass_k')} -> {spec.get('pass_k')}")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        val = round(sum(a.values()) / len(a), 4) if a else None
        verdict, note = "ok", f"n={len(a)}"
        if val is None:
            verdict = "missing"                       # an empty slice cannot vouch for anything
        elif "min" in sl and val < sl["min"]:
            verdict = "fail"
        elif "max" in sl and val > sl["max"]:
            verdict = "fail"
        if sl.get("no_significant_drop") and a and b:
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] n={len(keys)}"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
