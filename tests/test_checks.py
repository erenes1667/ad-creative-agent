import pytest
from adcreative.checks import (check_limits, trim_to_limit, banned_hits, overlay_matches, validate_manifest, PLATFORMS)
from conftest import good_copy


def test_limits_ok_and_boundaries():
    assert check_limits("meta", good_copy()["meta"]) == []
    it = {"headline": "x" * 40, "text": "y" * 125, "cta": "Play Now"}
    assert check_limits("meta", it) == []
    it["headline"] = "x" * 41
    assert "limit 40" in check_limits("meta", it)[0]


@pytest.mark.parametrize("p", list(PLATFORMS))
def test_each_platform_rejects_overlong_text_and_bad_cta(p):
    lim = PLATFORMS[p]
    it = {"headline": "ok", "text": "z" * (lim["text"] + 1), "cta": "Buy"}
    errs = check_limits(p, it)
    assert len(errs) == 2


def test_missing_field_is_error():
    assert check_limits("tiktok", {"headline": "", "text": "a", "cta": "Play Now"})


def test_trim_cuts_on_word_boundary():
    s = trim_to_limit("Rotate paper tiles to link the light, then relax", 30)
    assert len(s) <= 30 and not s.endswith((" ", ","))
    assert trim_to_limit("short", 30) == "short"


@pytest.mark.parametrize("text,label", [
    ("Win real cash today", "real-money claim"), ("Guaranteed fun", "guarantee"), ("The best puzzle game ever", "superlative claim"),
    ("99% of players fail", "unsourced statistic"), ("so addictive", "addiction framing"), ("Play now!!", "excess punctuation"),
    ("This is the #1 puzzle", "ranking claim")])
def test_banned_claims_caught(text, label):
    assert label in banned_hits(text)


def test_clean_copy_not_flagged():
    assert banned_hits("Rotate paper tiles. A new calm board every day. Free to play.") == []


def test_shouting_caps():
    assert "shouting caps" in banned_hits("PLAY NOW FREE FAST")


def test_overlay_match_ignores_order_case_punct():
    assert overlay_matches("Light the way Play Now", "play now, LIGHT the way")
    assert not overlay_matches("Light the way", "Lihgt the way")


def _manifest():
    c = {"id": "a1h1", "audience": "a", "angle": "x", "hook_line": "y", "copy": good_copy(), "checks": {}, "image": "images/a1h1.png"}
    return {"version": 1, "run_id": "r", "generated_at": "t", "fictional": True, "mode": "full", "image_backend": {}, "models": {},
            "brief": {}, "concepts": [c], "top": [{"id": "a1h1", "rank": 1, "score": 8, "reason": "because"}], "cost": {}}


def test_manifest_valid():
    validate_manifest(_manifest())


def test_manifest_rejections():
    m = _manifest(); del m["cost"]
    with pytest.raises(ValueError, match="missing keys"): validate_manifest(m)
    m = _manifest(); m["fictional"] = False
    with pytest.raises(ValueError, match="fictional"): validate_manifest(m)
    m = _manifest(); m["concepts"][0]["copy"]["meta"]["headline"] = "x" * 99
    with pytest.raises(ValueError, match="limit"): validate_manifest(m)
    m = _manifest(); m["top"][0]["id"] = "nope"
    with pytest.raises(ValueError, match="top"): validate_manifest(m)
    m = _manifest(); m["top"][0]["reason"] = ""
    with pytest.raises(ValueError, match="reason"): validate_manifest(m)
    m = _manifest(); del m["concepts"][0]["image"]
    with pytest.raises(ValueError, match="image"): validate_manifest(m)


def test_spearman_and_ranks():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    from adcreative.stats import spearman, ranks
    assert ranks([5, 5, 1]) == [2.5, 2.5, 1.0]
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0


def test_motion_cmd_chains_crossfades():
    from pathlib import Path
    from adcreative.motion import ffmpeg_cmd
    c = ffmpeg_cmd([Path("a.png"), Path("b.png"), Path("c.png")], Path("o.mp4"))
    g = c[c.index("-filter_complex") + 1]
    assert g.count("xfade") == 2 and c[c.index("-map") + 1] == "[x2]"


def test_build_docs_ledger_guard_exists():
    import pathlib
    assert "exists()" in (pathlib.Path(__file__).resolve().parent.parent / "scripts" / "build_docs.py").read_text()


def test_aspect_ok():
    from adcreative.checks import aspect_ok
    assert aspect_ok(1080, 1080) and not aspect_ok(1920, 1080) and not aspect_ok(600, 1080)
