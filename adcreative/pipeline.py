"""Explicit state machine: parse -> angles -> copy -> art -> images -> critic -> rank -> export."""
import json, time, uuid
from pathlib import Path
from . import agents as A
from .checks import PLATFORMS, banned_hits, copy_text, validate_manifest
from .export import write_contact_sheet
from .images import detect_backend, generate
from .llm import MODELS
from .memory import Memory

IMAGE_STEPS = ("art", "images", "critic", "rank")


def _timed(state, name, fn, llm):
    t0, c0 = time.time(), llm.spent
    fn()
    state["trace"].append({"step": name, "seconds": round(time.time() - t0, 1), "usd": round(llm.spent - c0, 4)})


def run(raw_brief: str, llm, mode="full", out_dir=None, memory=None, backend=None, use_memory=True, brief_id="brief", brand=None):
    memory = memory if memory is not None else Memory()
    out = Path(out_dir) if out_dir else Path("runs") / f"{brief_id}-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    S = {"trace": [], "concepts": []}
    backend = backend or (detect_backend() if mode == "full" else {"name": "none", "detail": "copy-only mode"})

    def s_parse():
        S["brief"] = A.parse_brief(llm, raw_brief)

    def s_angles():
        S["angles"], S["memory_report"] = A.angles(llm, S["brief"], memory, use_memory=use_memory)

    def s_copy():
        for ai, aud in enumerate(S["angles"]["audiences"]):
            for hi, item in enumerate(A.write_copy(llm, S["brief"], aud, brand)):
                fixed, stats = A.enforce_limits(llm, item["copy"])
                hook = aud["hooks"][hi]
                S["concepts"].append({
                    "id": f"a{ai+1}h{hi+1}", "audience": aud["name"], "audience_note": aud["description"],
                    "angle": hook["angle"], "hook_line": hook["hook_line"], "copy": fixed,
                    "checks": {"limits_raw_violations": stats["raw_violations"], "limits_fixed_by": stats["repaired_by"],
                               "limit_final_violations": stats.get("final_violations", 0),
                               "banned": banned_hits(copy_text(fixed)) + A.brand_hits(brand, copy_text(fixed))}})

    def s_art():
        by_aud = {}
        for c in S["concepts"]:
            by_aud.setdefault(c["audience"], []).append(c)
        for aud in S["angles"]["audiences"]:
            cs = by_aud[aud["name"]]
            for c, art in zip(cs, A.art_direct(llm, S["brief"], aud, cs)):
                art["cta_label"] = c["copy"]["meta"]["cta"]  # CTA comes from copy, never from the art agent
                c["art"] = art

    def s_images():
        for i, c in enumerate(S["concepts"]):
            png = out / "images" / f"{c['id']}.png"
            generate(backend, c["art"], {}, S["brief"]["palette"], i * 7 + 3, png)
            c["image"] = f"images/{c['id']}.png"

    def s_critic():
        for c in S["concepts"]:
            c["critic"] = A.critique(llm, S["brief"], c, out / c["image"])

    def s_rank():
        S["top"] = A.rank(S["concepts"])

    steps = [("parse", s_parse), ("angles", s_angles), ("copy", s_copy)]
    if mode == "full":
        steps += [("art", s_art), ("images", s_images), ("critic", s_critic), ("rank", s_rank)]
    else:
        S["top"] = []
    for name, fn in steps:
        _timed(S, name, fn, llm)
    manifest = build_manifest(S, mode, backend, llm, out.name)
    validate_manifest(manifest)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    write_contact_sheet(manifest, out / "contact_sheet.html")
    return manifest, out


def build_manifest(S, mode, backend, llm, run_id):
    used = {"parse": MODELS["parse"], "angles": MODELS["angles"], "copy": MODELS["copy"], "repair": MODELS["repair"]}
    if mode == "full":
        used.update(art=MODELS["art"], critic=MODELS["critic"])
    return {"version": 1, "run_id": run_id, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fictional": True, "mode": mode, "image_backend": backend, "models": used,
            "brief": S["brief"], "memory": S["memory_report"], "concepts": S["concepts"], "top": S["top"],
            "trace": S["trace"],
            "cost": {"usd": round(llm.spent, 4), "calls": llm.calls, "tokens_in": llm.tokens["in"], "tokens_out": llm.tokens["out"]}}
