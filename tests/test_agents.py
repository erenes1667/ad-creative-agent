import copy as cp
import pytest
from adcreative import agents as A
from adcreative.checks import check_limits, PLATFORMS
from adcreative.memory import Memory
from conftest import FakeLLM, good_copy, fake_embed


def _c(id_, aud, pol=9, leg=8, brand=8, msg=7, match=True, banned=(), final=0):
    return {"id": id_, "audience": aud, "checks": {"banned": list(banned), "limit_final_violations": final},
            "critic": {"legibility": leg, "brand_fit": brand, "policy_safety": pol, "message_match": msg, "summary": "ok",
                       "text_matches_intended": match}}


def test_ranker_orders_by_score_and_caps_per_audience():
    cs = [_c("1", "A", leg=10), _c("2", "A", leg=9), _c("3", "A", leg=8), _c("4", "B", leg=7), _c("5", "B", leg=6), _c("6", "C", leg=5.5), _c("7", "C", leg=5)]
    top = A.rank(cs)
    ids = [t["id"] for t in top]
    assert ids == ["1", "2", "4", "5", "6", "7"]  # third A concept dropped by the per-audience cap
    assert [t["rank"] for t in top] == [1, 2, 3, 4, 5, 6]
    assert all(t["reason"] for t in top)


def test_ranker_gates():
    cs = [_c("ok", "A"), _c("risky", "A", pol=5), _c("typo", "B", match=False), _c("banned", "B", banned=["guarantee"]), _c("long", "C", final=1)]
    top = A.rank(cs)
    assert [t["id"] for t in top] == ["ok"]
    by = {c["id"]: c["gate_failures"] for c in cs}
    assert "policy_safety" in by["risky"][0] and "typo" in by["typo"][0] and "banned" in by["banned"][0] and "limit" in by["long"][0]


def test_ranker_blocks_low_legibility_and_wrong_aspect():
    low, wide = _c("low", "A", leg=3), _c("wide", "B")
    wide["critic"]["aspect_ok"] = False
    A.rank([low, wide])
    assert "legibility" in low["gate_failures"][0] and "1:1" in wide["gate_failures"][0]


def test_ranker_never_returns_more_than_six():
    cs = [_c(str(i), "ABCD"[i % 4]) for i in range(12)]
    assert len(A.rank(cs, per_audience=9)) == 6


def test_enforce_limits_repairs_with_llm():
    bad = good_copy(); bad["meta"]["headline"] = "x" * 60
    fixed_by_llm = good_copy()
    llm = FakeLLM({"repair": fixed_by_llm})
    out, stats = A.enforce_limits(llm, bad)
    assert stats["raw_violations"] == 1 and stats["repaired_by"] == "llm" and stats["final_violations"] == 0


def test_enforce_limits_falls_back_to_trim_when_repair_still_long():
    bad = good_copy(); bad["tiktok"]["text"] = "word " * 40
    llm = FakeLLM({"repair": cp.deepcopy(bad)})
    out, stats = A.enforce_limits(llm, bad)
    assert stats["repaired_by"] == "trim" and stats["final_violations"] == 0
    assert all(not check_limits(p, out[p]) for p in PLATFORMS)


def test_enforce_limits_noop_when_clean():
    llm = FakeLLM()
    out, stats = A.enforce_limits(llm, good_copy())
    assert stats["raw_violations"] == 0 and llm.calls == 0


def test_enforce_fixes_bad_cta():
    bad = good_copy(); bad["google_uac"]["cta"] = "Buy Now"
    out, stats = A.enforce_limits(FakeLLM({"repair": cp.deepcopy(bad)}), bad)
    assert out["google_uac"]["cta"] in PLATFORMS["google_uac"]["ctas"]


def test_art_validator_rejects_long_overlay():
    bad = {"concepts": [{"image_prompt": "p", "motif": "burst", "layout": "top", "overlay_text": "this overlay is far too long to read"}] * 3}
    with pytest.raises(ValueError):
        A._v_art(bad)


def test_art_direct_appends_style_tokens():
    brief = FakeLLM().canned("parse")
    out = A.art_direct(FakeLLM(), brief, {"name": "a"}, [{"angle": "a", "hook_line": "h", "copy": good_copy()}] * 3)
    assert all("paper-cut; grain" in o["image_prompt"] for o in out)


def test_memory_retrieves_and_angle_agent_retries_on_repeat():
    notes = [{"id": "n1", "game": "g", "audience": "aud0", "angle": "angle 00", "hook": "hook 00"}]
    mem = Memory(notes, embedder=fake_embed)
    assert mem.retrieve("angle 00 hook 00 aud0")[0][0]["id"] == "n1"
    llm = FakeLLM()
    brief = llm.canned("parse")
    out, rep = A.angles(llm, brief, mem, threshold=0.5)
    assert rep["rounds"] == 2 and rep["max_sim_first"] > 0.5  # first draft repeated a past note, so it was regenerated
    out, rep = A.angles(FakeLLM(), brief, mem, threshold=0.5, use_memory=False)
    assert rep["rounds"] == 1


def test_critique_flags_text_mismatch(tmp_path):
    from PIL import Image
    p = tmp_path / "i.png"; Image.new("RGB", (8, 8)).save(p)
    llm = FakeLLM({"critic": {"text_read": "Lihgt the way Play Now", "legibility": 8, "brand_fit": 8, "policy_safety": 9, "message_match": 7, "summary": "s"}})
    c = A.critique(llm, FakeLLM().canned("parse"), {"copy": good_copy(), "art": {"overlay_text": "Light the way", "cta_label": "Play Now"}}, p)
    assert c["text_matches_intended"] is False
