import json, random
from adcreative import evals
from adcreative.stats import spearman


def test_stratified_pick_covers_range():
    rows = [{"orig_mean": i / 10, "id": str(i)} for i in range(108)]
    pick = evals.stratified_pick(rows, 20)
    assert len(pick) == 20 and len({p["id"] for p in pick}) == 20
    m = sorted(p["orig_mean"] for p in pick)
    assert m[0] < 1.0 and m[-1] > 9.8


def test_summarize_vision_and_agreement():
    mk = lambda n, cat, g: {"case": n, "category": cat, "gate_failures": g, "critic": {"text_matches_intended": not g}}
    a = {"cases": [mk("t", "typo", ["x"]), mk("c", "contrast", []), mk("ctl", "control", [])]}
    s = evals.summarize_vision(a["cases"])
    assert s["defects"] == 2 and s["caught"] == 1 and s["detection_rate"] == 0.5 and s["controls_flagged"] == 0
    assert s["by_category"]["contrast"] == {"caught": 0, "total": 1}
    b = {"cases": [mk("t", "typo", ["x"]), mk("c", "contrast", ["y"]), mk("ctl", "control", [])]}
    ag = evals.vision_agreement(a, b)
    assert ag["verdict_agree"] == 2 and ag["disagree_cases"] == ["c"]


def test_seeded_set_is_16_with_one_control():
    assert len(evals.SEEDED) == 16 and sum(c[1] == "control" for c in evals.SEEDED) == 1
    assert len({c[0] for c in evals.SEEDED}) == 16


def test_spearman_perfect_and_inverse():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0 and spearman([1, 2, 3], [3, 2, 1]) == -1.0


def test_repair_live_restores_limits(tmp_path, monkeypatch):
    from adcreative.checks import PLATFORMS
    import copy
    before = copy.deepcopy(PLATFORMS)
    from conftest import FakeLLM, good_copy
    monkeypatch.setattr(evals, "LLM", lambda scope: FakeLLM({"repair": good_copy("Short")}))
    root = evals.ROOT
    src = root / "runs" / "_t_manifest.json"
    src.write_text(json.dumps({"concepts": [{"copy": good_copy("A very long headline indeed for tiny limits")}]}))
    try:
        r = evals.repair_live(src)
    finally:
        src.unlink()
    assert PLATFORMS == before and r["stats"]["raw_violations"] > 0 and r["stats"]["repaired_by"] in ("llm", "trim")
    assert all(not v for v in r["final_errors"].values()) or r["stats"]["final_violations"] >= 0


def test_judge_check_blind_and_reports_spearman(monkeypatch):
    seen = []

    def fake_judge(llm, product, facts, not_true, items, role="judge"):
        seen.append((role, items))
        return [{"id": i["id"], **{d: 5.0 + (hash(i["id"]) % 5) for d in evals.DIMS}, "note": "n"} for i in items]

    class L:
        spent = 0.0
    monkeypatch.setattr(evals, "judge", fake_judge); monkeypatch.setattr(evals, "LLM", lambda scope: L())
    r = evals.judge_check()
    assert r["n"] == 20 and -1 <= r["overall_spearman"] <= 1 and set(r["per_dim"]) == set(evals.DIMS)
    assert all(role == "judge_check" for role, _ in seen)
    assert all(set(i) == {"id", "copy"} for _, items in seen for i in items)  # no first-judge scores leak into the prompt
