import argparse, json
from pathlib import Path
from .llm import LLM, ledger_total, SPEND_CAP_USD

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(prog="adcreative")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--brief", default="lantern-drift"); r.add_argument("--mode", choices=["copy", "full"], default="full"); r.add_argument("--brand", help="id of a kit in data/brands/")
    sub.add_parser("eval-copy"); sub.add_parser("calibrate")
    m = sub.add_parser("memory-demo"); m.add_argument("--threshold", type=float)
    v = sub.add_parser("vision-seeded"); v.add_argument("--role", default="critic", choices=["critic", "critic_check"])
    sub.add_parser("judge-check"); sub.add_parser("repair-live")
    mo = sub.add_parser("motion"); mo.add_argument("run_dir"); mo.add_argument("--out", default="motion.mp4")
    a = ap.parse_args()
    from . import evals
    save = lambda name, obj: (ROOT / "results" / name).write_text(json.dumps(obj, indent=2))
    if a.cmd == "run":
        from .pipeline import run
        raw = next(b for b in json.loads((ROOT / "data" / "briefs.json").read_text()) if b["id"] == a.brief)["raw"]
        brand = json.loads((ROOT / "data" / "brands" / f"{a.brand}.json").read_text()) if a.brand else None
        man, out = run(raw, LLM(scope=f"run:{a.brief}:{a.mode}"), mode=a.mode, brief_id=a.brief, brand=brand)
        print(out, "cost", man["cost"]["usd"], "top", [t["id"] for t in man["top"]])
    elif a.cmd == "eval-copy":
        save("copy_eval.json", evals.eval_copy()); print("saved copy_eval.json")
    elif a.cmd == "calibrate":
        save("judge_calibration.json", evals.calibrate(LLM(scope="calibrate"))); print("saved judge_calibration.json")
    elif a.cmd == "memory-demo":
        save("memory_demo.json", evals.memory_demo(threshold=a.threshold)); print("saved memory_demo.json")
    elif a.cmd == "vision-seeded":
        runs = sorted((ROOT / "runs").glob("lantern-drift-*/manifest.json"))
        man = json.loads(runs[-1].read_text())
        name = "vision_seeded.json" if a.role == "critic" else "vision_seeded_opus.json"
        f = ROOT / "results" / name
        r = evals.vision_seeded(man["brief"], man["brief"]["palette"], role=a.role, existing=json.loads(f.read_text()) if f.exists() else None)
        save(name, r); print("saved", name, r["summary"])
    elif a.cmd == "judge-check":
        r = evals.judge_check(); save("judge_check.json", r); print("saved judge_check.json", r["overall_spearman"])
    elif a.cmd == "repair-live":
        src = sorted((ROOT / "runs").glob("lantern-drift-*/manifest.json"))[-1]
        r = evals.repair_live(src); save("repair_live.json", r); print("saved repair_live.json", r["stats"])
    elif a.cmd == "motion":
        from .motion import make_clip
        if not (Path(a.run_dir) / "manifest.json").exists(): raise SystemExit(f"{a.run_dir} has no manifest.json. Pass a full run folder, e.g. runs/lantern-drift-<id>")
        print(make_clip(Path(a.run_dir), Path(a.out)))
    print(f"ledger total USD {ledger_total():.4f} of cap {SPEND_CAP_USD}")


main() if __name__ == "__main__" else None
