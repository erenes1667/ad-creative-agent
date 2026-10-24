"""Human check of the copy judge. `sheet` writes 20 blind items to fill in. `score` reads the filled sheet and writes Spearman vs the judge."""
import csv, json, random, sys
from pathlib import Path

from adcreative.stats import spearman

ROOT = Path(__file__).resolve().parent.parent
SHEET, OUT = ROOT / "data" / "hand_score_sheet.csv", ROOT / "results" / "hand_score.json"
DIMS = ("hook_strength", "platform_fit")


def judge_rows():
    ev = json.loads((ROOT / "results" / "copy_eval.json").read_text()); rows = []
    for b in ev["briefs"]:
        man = json.loads((ROOT / "runs" / "eval" / b["id"] / "manifest.json").read_text())
        copy = {c["id"]: c["copy"]["meta"] for c in man["concepts"]}
        rows += [{"key": f"{b['id']}/{r['id']}", "meta": copy[r["id"]], **{d: r[d] for d in DIMS}} for r in b["judge_rows"]]
    return rows


def make_sheet(n=20, seed=7):
    pick = random.Random(seed).sample(judge_rows(), n)
    with SHEET.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["key", "meta_headline", "meta_text", "hook_strength_0_10", "platform_fit_0_10"])
        for r in pick: w.writerow([r["key"], r["meta"]["headline"], r["meta"]["text"], "", ""])


def score():
    judge = {r["key"]: r for r in judge_rows()}
    rows = [r for r in csv.DictReader(SHEET.open()) if r["hook_strength_0_10"] and r["platform_fit_0_10"]]
    if not rows:
        raise SystemExit("sheet not filled in yet: fill data/hand_score_sheet.csv first")
    res = {"n": len(rows), "rater": "Claude, at the owner's request, blind to judge scores. Not a human."}
    for d, col in zip(DIMS, ("hook_strength_0_10", "platform_fit_0_10")):
        h = [float(r[col]) for r in rows]; j = [judge[r["key"]][d] for r in rows]
        res[d] = {"spearman": spearman(h, j), "rater_mean": round(sum(h) / len(h), 2), "judge_mean": round(sum(j) / len(j), 2)}
    OUT.write_text(json.dumps(res, indent=2)); return res


if __name__ == "__main__":
    if sys.argv[1:] == ["sheet"]: make_sheet(); print("wrote", SHEET)
    else: print(score())
