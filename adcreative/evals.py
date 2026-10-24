"""LLM-as-judge, judge calibration, copy-only eval, memory demo, seeded vision test."""
import json, random, statistics as st
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from . import agents as A
from .checks import check_limits, banned_hits, copy_text, PLATFORMS
from .llm import LLM, MODELS
from .memory import Memory
from .pipeline import run

ROOT = Path(__file__).resolve().parent.parent
DIMS = ("hook_strength", "clarity", "policy_safety", "platform_fit")
RUBRIC = """Score each ad concept 0-10 on four dimensions (10 is best). Be strict. Use the full range.
hook_strength: does the first line stop a scroller and name a concrete reason to care. Generic praise scores low.
clarity: after reading, does a stranger know what the product is and does, in plain words.
policy_safety: 10 means no ad-policy risk. Deduct hard for real-money or prize claims, guarantees, invented statistics,
 rankings, claims of features the product does not have (see NOT TRUE), shouting or excess punctuation.
platform_fit: does each of the three platform versions read natively for its platform and stay concise and distinct,
 not three copies of one text, and not bloated."""


def _v_judge(n):
    def v(o):
        rows = o["scores"]
        if len(rows) != n:
            raise ValueError(f"need {n} score rows")
        for r in rows:
            for d in DIMS:
                if not 0 <= float(r[d]) <= 10:
                    raise ValueError(f"{d} out of range")
            r["id"], r["note"]
    return v


def judge(llm, product, facts, not_true, items, role="judge"):
    """items: list of {id, copy}. One call, scores for all. Judge never sees deterministic check results."""
    sys = "You are a strict ad-quality judge. The product is fictional. Reply with JSON only."
    user = f"""{RUBRIC}

Product: {product}
True facts: {facts}
NOT TRUE: {not_true}

Concepts:
{json.dumps(items)}

Return JSON: {{"scores":[{{"id","hook_strength","clarity","policy_safety","platform_fit","note":"one short sentence"}} per concept, same ids]}}"""
    return llm.json(role, sys, user, _v_judge(len(items)), max_tokens=300 + 110 * len(items), tag="judge")["scores"]


def calibrate(llm, passes=2):
    cal = json.loads((ROOT / "data" / "judge_calibration.json").read_text())
    items = cal["items"]
    runs = []
    for p in range(passes):
        order = items[:]
        random.Random(p).shuffle(order)
        sc = judge(llm, cal["product"], cal["facts"], ["real-money prizes", "multiplayer", "leaderboards"],
                   [{"id": i["id"], "copy": i["copy"]} for i in order])
        runs.append({r["id"]: r for r in sc})
    rows, weak_hit, strong_ok = [], [], []
    for it in items:
        scores = {d: st.mean(float(r[it["id"]][d]) for r in runs) for d in DIMS}
        rows.append({"id": it["id"], "kind": it["kind"], "expected_low": it["low"], "scores": {k: round(v, 2) for k, v in scores.items()},
                     "mean": round(st.mean(scores.values()), 2), "note": runs[0][it["id"]]["note"]})
        if it["kind"] == "weak":
            weak_hit.append(all(scores[d] <= 4 for d in it["low"]))
        else:
            strong_ok.append(min(scores.values()) >= 6)
    diffs = [abs(float(runs[0][i["id"]][d]) - float(runs[1][i["id"]][d])) for i in items for d in DIMS] if passes > 1 else [0]
    return {"items": rows, "weak_flaw_found": f"{sum(weak_hit)}/{len(weak_hit)}", "strong_all_dims_ge6": f"{sum(strong_ok)}/{len(strong_ok)}",
            "mean_strong": round(st.mean(r["mean"] for r in rows if r["kind"] == "strong"), 2),
            "mean_weak": round(st.mean(r["mean"] for r in rows if r["kind"] == "weak"), 2),
            "order_sensitivity_mean_abs_diff": round(st.mean(diffs), 3), "passes": passes, "judge_model": __import__("adcreative.llm", fromlist=["MODELS"]).MODELS["judge"],
            "cost_usd": round(llm.spent, 4)}


def eval_one(b, memory):
    llm = LLM(scope=f"eval:{b['id']}")
    out = ROOT / "runs" / "eval" / b["id"]
    man, _ = run(b["raw"], llm, mode="copy", out_dir=out, memory=memory, brief_id=b["id"])
    pipe_cost = llm.spent
    cs = man["concepts"]
    items = [{"id": c["id"], "copy": c["copy"]} for c in cs]
    sc = judge(llm, man["brief"]["name"], man["brief"]["facts"], man["brief"]["not_true"], items)
    avg = {d: round(st.mean(float(r[d]) for r in sc), 2) for d in DIMS}
    return {"id": b["id"], "name": man["brief"]["name"], "concepts": len(cs),
            "raw_limit_violations": sum(c["checks"]["limits_raw_violations"] for c in cs),
            "concepts_with_raw_violation": sum(c["checks"]["limits_raw_violations"] > 0 for c in cs),
            "final_limit_violations": sum(c["checks"]["limit_final_violations"] for c in cs),
            "fixed_by": {k: sum(c["checks"]["limits_fixed_by"] == k for c in cs) for k in ("llm", "trim")},
            "banned_claim_concepts": sum(bool(c["checks"]["banned"]) for c in cs),
            "memory_max_sim_first": man["memory"]["max_sim_first"], "memory_max_sim_final": man["memory"]["max_sim_final"],
            "memory_rounds": man["memory"]["rounds"],
            "judge_avg": avg, "judge_mean": round(st.mean(avg.values()), 2),
            "judge_min_concept": round(min(st.mean(float(r[d]) for d in DIMS) for r in sc), 2),
            "judge_rows": sc, "cost_pipeline_usd": round(pipe_cost, 4), "cost_total_usd": round(llm.spent, 4)}


def eval_copy(workers=4):
    briefs = json.loads((ROOT / "data" / "briefs.json").read_text())
    mem = Memory()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda b: eval_one(b, mem), briefs))
    tot = round(sum(r["cost_total_usd"] for r in res), 4)
    summ = {"briefs": len(res), "total_cost_usd": tot, "mean_cost_per_brief_usd": round(tot / len(res), 4),
            "judge_mean_over_briefs": round(st.mean(r["judge_mean"] for r in res), 2),
            "judge_avg_by_dim": {d: round(st.mean(r["judge_avg"][d] for r in res), 2) for d in DIMS},
            "raw_limit_violations_total": sum(r["raw_limit_violations"] for r in res),
            "final_limit_violations_total": sum(r["final_limit_violations"] for r in res),
            "concepts_total": sum(r["concepts"] for r in res),
            "concepts_with_raw_violation_total": sum(r["concepts_with_raw_violation"] for r in res),
            "banned_claim_concepts_total": sum(r["banned_claim_concepts"] for r in res)}
    return {"summary": summ, "briefs": res}


def memory_demo(trials=3, threshold=None):
    from .memory import SIM_THRESHOLD
    thr = threshold or SIM_THRESHOLD
    llm = LLM(scope="memory-demo")
    raw = next(b for b in json.loads((ROOT / "data" / "briefs.json").read_text()) if b["id"] == "lantern-drift")["raw"]
    brief = A.parse_brief(llm, raw)
    mem = Memory()
    arms = {}
    for arm, use in (("memory_off", False), ("memory_on", True)):
        arms[arm] = []
        for t in range(trials):
            out, rep = A.angles(llm, brief, mem, threshold=thr, use_memory=use)
            rows = []
            for a in out["audiences"]:
                for h in a["hooks"]:
                    s, nid = mem.max_sim(A.angle_text(a, h))
                    rows.append({"audience": a["name"], "hook_line": h["hook_line"], "angle": h["angle"], "closest_note": nid, "sim": round(s, 3)})
            arms[arm].append({"report": rep, "angles": rows, "max_sim": max(r["sim"] for r in rows),
                              "mean_sim": round(st.mean(r["sim"] for r in rows), 3), "over_threshold": sum(r["sim"] > thr for r in rows)})
    return {"threshold": thr, "trials": trials, "retrieved_for_brief": [{"id": n["id"], "sim": round(s, 3), "angle": n["angle"]} for n, s in mem.retrieve(f"{brief['name']} {brief['category']} {brief['pitch']}", 6)],
            "arms": arms, "cost_usd": round(llm.spent, 4)}


HEAD = "Light the way home"
# (case, category, text meant, text drawn, ink override, resize to (w, h) or None). Control has category "control".
SEEDED = [
    ("typo", "typo", HEAD, "Lihgt the way home", None, None),
    ("real_cash", "claim", "Win real cash prizes", "Win real cash prizes", None, None),
    ("fake_multiplayer", "claim", "Beat friends live online", "Beat friends live online", None, None),
    ("control", "control", HEAD, HEAD, None, None),
    ("typo_2", "typo", "Rotate tiles, link the light", "Rotate tiels, link the light", None, None),
    ("typo_3", "typo", "A calm puzzle for tonight", "A calm puzle for tonihgt", None, None),
    ("typo_4", "typo", "Play free on iOS and Android", "Play fere on iOS and Andriod", None, None),
    ("low_contrast_1", "contrast", HEAD, HEAD, "#2F3470", None),
    ("low_contrast_2", "contrast", "Rotate tiles, link the light", "Rotate tiles, link the light", "#454A86", None),
    ("low_contrast_3", "contrast", "A calm puzzle for tonight", "A calm puzzle for tonight", "#262B5C", None),
    ("claim_leaderboard", "claim", "Climb the global leaderboard", "Climb the global leaderboard", None, None),
    ("claim_timed", "claim", "Beat the clock in timed rounds", "Beat the clock in timed rounds", None, None),
    ("claim_combat", "claim", "Battle monsters in combat mode", "Battle monsters in combat mode", None, None),
    ("aspect_wide", "aspect", HEAD, HEAD, None, (1920, 1080)),
    ("aspect_tall", "aspect", HEAD, HEAD, None, (600, 1080)),
    ("aspect_crop", "aspect", HEAD, HEAD, None, (1080, 607)),
]
DEFECT = lambda cat: cat != "control"


def summarize_vision(cases):
    cats = {}
    for r in cases:
        d = cats.setdefault(r["category"], {"caught": 0, "total": 0})
        d["total"] += 1
        d["caught"] += bool(r["gate_failures"])
    defects = [r for r in cases if DEFECT(r["category"])]
    ctrl = [r for r in cases if not DEFECT(r["category"])]
    return {"images": len(cases), "defects": len(defects), "caught": sum(bool(r["gate_failures"]) for r in defects),
            "detection_rate": round(sum(bool(r["gate_failures"]) for r in defects) / len(defects), 3),
            "controls": len(ctrl), "controls_flagged": sum(bool(r["gate_failures"]) for r in ctrl), "by_category": cats}


def vision_seeded(brief, palette, role="critic", existing=None, out_name=None):
    """16 images with known defects (15 defects, 1 clean control). `existing` is a saved result: cases already in it are reused,
    so a re-run only pays for new images. role picks the model: critic (Sonnet) or critic_check (Opus)."""
    from PIL import Image
    from .render import render_svg_ad
    out = ROOT / "runs" / "seeded"
    llm = LLM(scope=f"vision-seeded:{role}")
    base = {"motif": "orb_glow", "layout": "bottom", "cta_label": "Play Now"}
    have = {r["case"]: r for r in (existing or {}).get("cases", [])}
    res = []
    for name, cat, intended, drawn, ink, size in SEEDED:
        if name in have:
            r = dict(have[name]); r["category"] = cat; res.append(r); continue
        png = render_svg_ad({**base, "overlay_text": drawn, **({"ink": ink} if ink else {})}, palette, 5, out / f"{name}.png")
        if size:
            with Image.open(png) as im:
                (im.resize(size) if size[1] != 607 else im.crop((0, 0, 1080, 607))).save(png)
        concept = {"copy": {"meta": {"headline": HEAD}}, "art": {"overlay_text": intended, "cta_label": "Play Now"},
                   "checks": {"banned": [], "limit_final_violations": 0}}
        concept["critic"] = A.critique(llm, brief, concept, png, role=role)
        res.append({"case": name, "category": cat, "image": f"seeded/{name}.png", "intended": intended, "drawn": drawn,
                    "critic": concept["critic"], "gate_failures": A.gate_failures(concept)})
    for r in res:  # re-apply the current gates to reused cases too
        r["gate_failures"] = A.gate_failures({"checks": {"banned": [], "limit_final_violations": 0}, "critic": r["critic"]})
    return {"cases": res, "summary": summarize_vision(res), "model": MODELS[role], "cost_usd": round(llm.spent, 4)}


def vision_agreement(a, b):
    """Case-by-case agreement between two critic runs on the same images. Compares the gate verdict and the text read."""
    bb = {r["case"]: r for r in b["cases"]}
    rows = [(r["case"], bool(r["gate_failures"]) == bool(bb[r["case"]]["gate_failures"]),
             r["critic"]["text_matches_intended"] == bb[r["case"]]["critic"]["text_matches_intended"]) for r in a["cases"] if r["case"] in bb]
    return {"n": len(rows), "verdict_agree": sum(x[1] for x in rows), "text_match_agree": sum(x[2] for x in rows),
            "disagree_cases": [x[0] for x in rows if not x[1]]}


def stratified_pick(rows, n=20, seed=11):
    """Sort by the original judge mean, cut into n equal slices, take one random item per slice. Covers low, mid and high scores."""
    rnd = random.Random(seed)
    srt = sorted(rows, key=lambda r: r["orig_mean"])
    return [rnd.choice(srt[i * len(srt) // n:(i + 1) * len(srt) // n]) for i in range(n)]


def judge_check(role="judge_check", n=20):
    """Blind re-score of a stratified subset by a second model. The second model sees only the copy, facts and NOT TRUE list,
    never the first judge's scores. Reports Spearman against the first judge. Model-vs-model agreement is not human agreement."""
    from .stats import spearman
    ev = json.loads((ROOT / "results" / "copy_eval.json").read_text())
    rows = []
    for b in ev["briefs"]:
        man = json.loads((ROOT / "runs" / "eval" / b["id"] / "manifest.json").read_text())
        cp = {c["id"]: c["copy"] for c in man["concepts"]}
        for r in b["judge_rows"]:
            rows.append({"brief": b["id"], "id": r["id"], "copy": cp[r["id"]], "orig": {d: float(r[d]) for d in DIMS},
                         "orig_mean": st.mean(float(r[d]) for d in DIMS), "bm": man["brief"]})
    pick = stratified_pick(rows, n)
    llm = LLM(scope="judge-check")
    new = {}
    for bid in sorted({p["brief"] for p in pick}):
        grp = [p for p in pick if p["brief"] == bid]
        bm = grp[0]["bm"]
        sc = judge(llm, bm["name"], bm["facts"], bm["not_true"], [{"id": p["id"], "copy": p["copy"]} for p in grp], role=role)
        new.update({(bid, r["id"]): r for r in sc})
    out = {"n": len(pick), "model": MODELS[role], "first_judge_model": MODELS["judge"], "per_dim": {}, "items": []}
    for d in DIMS:
        o = [p["orig"][d] for p in pick]; m = [float(new[(p["brief"], p["id"])][d]) for p in pick]
        out["per_dim"][d] = {"spearman": spearman(o, m), "first_mean": round(st.mean(o), 2), "second_mean": round(st.mean(m), 2)}
    om = [p["orig_mean"] for p in pick]; mm = [st.mean(float(new[(p["brief"], p["id"])][d]) for d in DIMS) for p in pick]
    out["overall_spearman"] = spearman(om, mm)
    out["items"] = [{"key": f"{p['brief']}/{p['id']}", "first": round(a, 2), "second": round(b, 2)} for p, a, b in zip(pick, om, mm)]
    out["cost_usd"] = round(llm.spent, 4)
    return out


def repair_live(source_manifest):
    """Force the length-limit repair path on a real call. Real copy from a past run is checked against deliberately tiny limits."""
    from .checks import PLATFORMS
    import copy as cp
    man = json.loads(Path(source_manifest).read_text())
    original = man["concepts"][0]["copy"]
    tiny = {"meta": (16, 40), "tiktok": (14, 30), "google_uac": (14, 30)}
    saved = cp.deepcopy(PLATFORMS)
    llm = LLM(scope="repair-live")
    try:
        for p, (h, t) in tiny.items():
            PLATFORMS[p]["headline"], PLATFORMS[p]["text"] = h, t
        fixed, stats = A.enforce_limits(llm, cp.deepcopy(original))
        final = {p: A.check_limits(p, fixed[p]) for p in PLATFORMS}
    finally:
        for p in PLATFORMS:
            PLATFORMS[p].update(saved[p])
    return {"tiny_limits_headline_text": tiny, "before": original, "after": fixed, "stats": stats, "final_errors": final,
            "repair_calls": llm.calls, "cost_usd": round(llm.spent, 4), "source": str(Path(source_manifest).relative_to(ROOT))}
