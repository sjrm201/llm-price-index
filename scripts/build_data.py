#!/usr/bin/env python3
"""
Daily LLM token-price snapshot -> dashboard data.

Source: OpenRouter public models API (no key needed). Prices are converted
from $/token to $/1M tokens. Each run:
  1. fetches the catalogue (or reads --input for offline/testing)
  2. writes data/snapshots/YYYY-MM-DD.json (compact, one per UTC day)
  3. rebuilds history + change log from ALL snapshots (deterministic)
  4. writes data/latest.json, data/history.csv and data/data.js (what index.html loads)

Stdlib only so the GitHub Action needs no pip install.
"""
import argparse
import csv
import datetime as dt
import json
import pathlib
import sys
import urllib.request

API = "https://openrouter.ai/api/v1/models"
ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SNAP = DATA / "snapshots"
MIN_MODELS = 40          # sanity guard: refuse to write if the API returns junk
MAX_CHANGES_KEPT = 500


def fetch(src):
    if src:
        return json.loads(pathlib.Path(src).read_text())["data"]
    req = urllib.request.Request(API, headers={"User-Agent": "llm-price-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["data"]


def per_m(v):
    """$/token string -> $/1M tokens float. Negative / missing => None (variable pricing)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x < 0 else round(x * 1e6, 6)


def normalize(raw):
    rows = []
    for m in raw:
        mid = m["id"]
        p = m.get("pricing") or {}
        full = m.get("name") or mid
        if ":" in full:
            lab, name = (s.strip() for s in full.split(":", 1))
        else:
            lab, name = mid.lstrip("~").split("/")[0], full
        inp, out = per_m(p.get("prompt")), per_m(p.get("completion"))

        long_ctx = None
        for o in p.get("overrides") or []:
            if "min_prompt_tokens" in o:
                long_ctx = {"above": o["min_prompt_tokens"],
                            "input": per_m(o.get("prompt")),
                            "output": per_m(o.get("completion"))}
                break

        flags = []
        if mid.endswith(":free") or (inp == 0 and out == 0):
            flags.append("free")
        if mid.endswith(":batch"):
            flags.append("batch")
        if mid.startswith("~"):
            flags.append("alias")
        if inp is None or out is None:
            flags.append("variable")

        rows.append({
            "id": mid, "name": name, "lab": lab,
            "input": inp, "output": out,
            "cache_read": per_m(p.get("input_cache_read")),
            "cache_write": per_m(p.get("input_cache_write")),
            "context": m.get("context_length"),
            "created": m.get("created"),
            "long_ctx": long_ctx,
            "flags": flags,
        })
    rows.sort(key=lambda r: (r["lab"].lower(), r["id"]))
    return rows


def compact(rows):
    # snapshot keeps only what's needed to rebuild history (~25 KB/day)
    return {r["id"]: [r["input"], r["output"], r["cache_read"]] for r in rows}


def load_snapshots():
    out = []
    for f in sorted(SNAP.glob("*.json")):
        out.append((f.stem, json.loads(f.read_text())))
    return out


def build_history(snaps):
    """history[id] = [[date, in, out], ...] only at points where price changed."""
    hist, changes, first_seen = {}, [], {}
    prev = None
    for date, snap in snaps:
        for mid, (i, o, _c) in snap.items():
            first_seen.setdefault(mid, date)
            h = hist.setdefault(mid, [])
            if not h or h[-1][1] != i or h[-1][2] != o:
                h.append([date, i, o])
        if prev is not None:
            pdate, psnap = prev
            for mid, (i, o, _c) in snap.items():
                if mid not in psnap:
                    changes.append({"date": date, "id": mid, "type": "new", "input": i, "output": o})
                else:
                    pi, po, _ = psnap[mid]
                    if (pi, po) != (i, o):
                        changes.append({"date": date, "id": mid, "type": "price",
                                        "input": i, "output": o, "prev_input": pi, "prev_output": po})
            for mid in psnap:
                if mid not in snap:
                    changes.append({"date": date, "id": mid, "type": "removed"})
        prev = (date, snap)
    changes.sort(key=lambda c: c["date"], reverse=True)
    return hist, changes[:MAX_CHANGES_KEPT], first_seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="read an OpenRouter /models JSON file instead of calling the API")
    ap.add_argument("--date", help="override snapshot date (YYYY-MM-DD), for backfill/testing")
    args = ap.parse_args()

    raw = fetch(args.input)
    rows = normalize(raw)
    if len(rows) < MIN_MODELS:
        sys.exit(f"Only {len(rows)} models returned (< {MIN_MODELS}); refusing to overwrite data.")

    now = dt.datetime.now(dt.timezone.utc)
    date = args.date or now.strftime("%Y-%m-%d")
    SNAP.mkdir(parents=True, exist_ok=True)
    (SNAP / f"{date}.json").write_text(json.dumps(compact(rows), separators=(",", ":")))

    snaps = load_snapshots()
    hist, changes, first_seen = build_history(snaps)
    removed = {c["id"] for c in changes if c["type"] == "removed" and c["date"] == date}

    for r in rows:
        r["first_seen"] = first_seen.get(r["id"], date)

    payload = {
        "as_of": date,
        "generated_at": now.isoformat(timespec="seconds"),
        "source": "OpenRouter models API (list prices, USD per 1M tokens)",
        "snapshot_count": len(snaps),
        "first_snapshot": snaps[0][0] if snaps else date,
        "models": rows,
        "history": {k: v for k, v in hist.items() if k not in removed},
        "changes": changes,
    }
    (DATA / "latest.json").write_text(json.dumps(payload, separators=(",", ":")))
    (DATA / "data.js").write_text("window.LLM_DATA=" + json.dumps(payload, separators=(",", ":")) + ";\n")

    with open(DATA / "history.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "model_id", "input_usd_per_1m", "output_usd_per_1m", "cache_read_usd_per_1m"])
        for d, snap in snaps:
            for mid, (i, o, c) in sorted(snap.items()):
                w.writerow([d, mid, i, o, c])

    n_today = sum(1 for c in changes if c["date"] == date)
    print(f"{date}: {len(rows)} models, {len(snaps)} snapshots, {n_today} changes today")


if __name__ == "__main__":
    main()
