"""Run the repo's vision critic on the 6 ChatGPT images (made by hand, no text in image). Writes results/vision_real_gpt.json."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adcreative import agents as A
from adcreative.llm import LLM

run = ROOT / "runs" / "tidebreak-20261024-021544"
man = json.loads((run / "manifest.json").read_text())
cs = {c["id"]: c for c in man["concepts"]}
llm = LLM(scope="vision-real-gpt")
out = []
for t in man["top"]:
    c = json.loads(json.dumps(cs[t["id"]]))
    c["art"] = {**c["art"], "overlay_text": "", "cta_label": ""}  # images have no text by design
    png = run / "images_gpt" / f"{c['id']}.png"
    c["critic"] = A.critique(llm, man["brief"], c, png, role="critic")
    out.append({"id": c["id"], "rank_svg_run": t["rank"], "image": f"runs/{run.name}/images_gpt/{c['id']}.png",
                "critic": c["critic"], "gate_failures": A.gate_failures(c)})
res = {"run": run.name, "images_from": "ChatGPT web app, run by hand 2026-10-24", "model": "claude-sonnet-5-5",
       "cases": out, "cost_usd": round(llm.spent, 4)}
(ROOT / "results" / "vision_real_gpt.json").write_text(json.dumps(res, indent=2))
for o in out:
    k = o["critic"]
    print(o["id"], k["legibility"], k["brand_fit"], k["policy_safety"], k["message_match"], o["gate_failures"], "|", k["summary"])
print("cost", res["cost_usd"])
