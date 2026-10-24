"""Build docs/index.html from run artifacts. Every number on the page is read from a file in results/ or runs/."""
import html, json, shutil, statistics as st, sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
R, D = ROOT / "results", ROOT / "docs"
e = html.escape
(D / "assets").mkdir(parents=True, exist_ok=True)

run_dir = sorted((ROOT / "runs").glob("lantern-drift-*"))[-1]
man = json.loads((run_dir / "manifest.json").read_text())
mem = json.loads((R / "memory_demo.json").read_text())
ev = json.loads((R / "copy_eval.json").read_text())
cal = json.loads((R / "judge_calibration.json").read_text())
vs = json.loads((R / "vision_seeded.json").read_text())
vsum = vs["summary"]
rl = json.loads((R / "repair_live.json").read_text())
ledger = [json.loads(l) for l in (R / "cost_log.jsonl").read_text().splitlines()] if (R / "cost_log.jsonl").exists() else []
total = round(sum(l["usd"] for l in ledger), 2)


def asset(src: Path, name):
    im = Image.open(src).convert("RGB"); im.thumbnail((640, 640))
    im.save(D / "assets" / name, "JPEG", quality=84)
    return f"assets/{name}"

by_id = {c["id"]: c for c in man["concepts"]}
cards = ""
for t in man["top"]:
    c = by_id[t["id"]]
    img = asset(run_dir / c["image"], f"top-{t['rank']}.jpg")
    m = c["copy"]
    cards += f"""<article class="card"><img src="{img}" width="640" height="640" alt="Ad image {t['rank']}: {e(c['art']['overlay_text'])}" loading="lazy">
<p class="ph">Placeholder SVG art, not an image model</p><h3>#{t['rank']} &middot; score {t['score']}</h3>
<dl><dt>Meta</dt><dd>{e(m['meta']['headline'])} <span class="mut">({len(m['meta']['headline'])}/40)</span><br>{e(m['meta']['text'])} <span class="mut">({len(m['meta']['text'])}/125)</span> [{e(m['meta']['cta'])}]</dd>
<dt>TikTok</dt><dd>{e(m['tiktok']['headline'])} / {e(m['tiktok']['text'])}</dd>
<dt>Google UAC</dt><dd>{e(m['google_uac']['headline'])} / {e(m['google_uac']['text'])}</dd></dl>
<p class="mut">Audience: {e(c['audience'])}. Critic: L {c['critic']['legibility']}, B {c['critic']['brand_fit']}, P {c['critic']['policy_safety']}, M {c['critic']['message_match']}.</p>
<p class="why">{e(t['reason'])}</p></article>"""

tb_dir = ROOT / "runs" / "tidebreak-20261024-021544"
tb = json.loads((tb_dir / "manifest.json").read_text())
tb_by = {c["id"]: c for c in tb["concepts"]}
gpt = json.loads((R / "vision_real_gpt.json").read_text())
gpt_cards = ""
gpt_rows = ""
for g in gpt["cases"]:
    c = tb_by[g["id"]]; k = g["critic"]; sv = c["critic"]
    img = asset(ROOT / g["image"], f"gpt-{g['id']}.jpg")
    gpt_cards += f"""<article class="card"><img src="{img}" width="640" height="640" alt="GPT image for Tidebreak concept {g['id']}: {e(c['hook_line'])}" loading="lazy">
<h3>{e(c['hook_line'])}</h3><p class="mut">Concept {g['id']}, rank {g['rank_svg_run']} in the SVG run. Critic: L {k['legibility']}, B {k['brand_fit']}, P {k['policy_safety']}, M {k['message_match']}.</p>
<p class="why">{e(k['summary'])}</p></article>"""
    gpt_rows += f"<tr><td>{g['id']}</td><td>{sv['legibility']} / {sv['brand_fit']} / {sv['policy_safety']} / {sv['message_match']}</td><td>{k['legibility']} / {k['brand_fit']} / {k['policy_safety']} / {k['message_match']}</td><td>{e('; '.join(g['gate_failures']) or 'none')}</td></tr>"

seeded = ""
for c in vs["cases"]:
    img = asset(ROOT / "runs" / c["image"], f"seed-{c['case']}.jpg")
    verdict = "; ".join(c["gate_failures"]) or "passed all gates"
    seeded += f"""<article class="card sm"><img src="{img}" width="640" height="640" alt="Seeded test: {e(c['case'])}" loading="lazy"><h3>{e(c['case'])}</h3>
<p class="mut">Drawn: {e(c['drawn'])}<br>Meant: {e(c['intended'])}</p><p>Critic read: {e(c['critic']['text_read'])}</p><p><b>Gate:</b> {e(verdict)}</p></article>"""

def arm(name):
    ts = mem["arms"][name]
    return (round(st.mean(t["max_sim"] for t in ts), 3), round(st.mean(t["mean_sim"] for t in ts), 3),
            sum(t["over_threshold"] for t in ts), sum(t["report"]["rounds"] == 2 for t in ts))
off, on = arm("memory_off"), arm("memory_on")

rows = "".join(f"<tr><td>{e(b['name'])}</td><td>{b['judge_avg']['hook_strength']}</td><td>{b['judge_avg']['clarity']}</td><td>{b['judge_avg']['policy_safety']}</td><td>{b['judge_avg']['platform_fit']}</td><td>{b['raw_limit_violations']}</td><td>{b['banned_claim_concepts']}</td><td>${b['cost_total_usd']:.3f}</td></tr>" for b in ev["briefs"])
S = ev["summary"]
calrows = "".join(f"<tr><td>{r['id']}</td><td>{r['kind']}</td><td>{', '.join(r['expected_low']) or '-'}</td><td>{r['scores']['hook_strength']}</td><td>{r['scores']['clarity']}</td><td>{r['scores']['policy_safety']}</td><td>{r['scores']['platform_fit']}</td></tr>" for r in cal["items"])
tr = "".join(f"<tr><td>{t['step']}</td><td>{t['seconds']} s</td><td>${t['usd']:.3f}</td></tr>" for t in man["trace"])
date = man["generated_at"][:10]
models = ", ".join(sorted(set(man["models"].values())))

# diagram: vertical, real step names and models from the manifest
steps = [("1 Brief parser", man["models"]["parse"], "raw brief to JSON: facts, not_true, palette"),
         ("2 Audience and angle agent", man["models"]["angles"], "3 audiences x 3 hooks, avoids retrieved past angles"),
         ("3 Copy agent", man["models"]["copy"], "Meta, TikTok, Google UAC copy per concept"),
         ("3b Limit enforcer (code)", "no LLM, repair: " + man["models"]["repair"], "check lengths, one repair call, then trim"),
         ("4 Art director", man["models"]["art"], "image prompt plus style tokens, motif, overlay text"),
         ("5 Image generation", "no LLM in fallback: " + man["image_backend"]["name"], "pluggable: OpenAI, diffusion server, SVG fallback"),
         ("6 Vision critic", man["models"]["critic"], "reads the image: legibility, brand, policy, text match"),
         ("7 Ranker (code)", "no LLM", "gates, weighted score, top 6, max 2 per audience"),
         ("8 Export", "no LLM", "manifest.json plus contact_sheet.html"),
         ("9 Motion (optional)", "no LLM, ffmpeg", "6.5 s clip from top 3 images")]
H = len(steps) * 92 + 100
svg = '<svg viewBox="0 0 460 %d" role="img" aria-label="Pipeline diagram: ten steps from brief parser to export, a creative memory feeding the angle agent and a cost ledger under every model call.">' % H
svg += '<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0 0L8 4L0 8z" fill="var(--mut)"/></marker></defs>'
for i, (n, m, d) in enumerate(steps):
    y = 6 + i * 92
    cls = "code" if "no LLM" in m else "llm"
    svg += f'<rect class="box {cls}" x="10" y="{y}" width="440" height="70" rx="10"/><text class="t1" x="24" y="{y+25}">{e(n)}</text><text class="t2" x="24" y="{y+46}">{e(m)}</text><text class="t3" x="24" y="{y+63}">{e(d[:58])}</text>'
    svg += f'<line x1="230" y1="{y+70}" x2="230" y2="{y+90}" stroke="var(--mut)" stroke-width="2" marker-end="url(#ar)"/>' if i < len(steps) - 1 else ''
y = 6 + len(steps) * 92
svg += f'<rect class="box mem" x="10" y="{y}" width="215" height="76" rx="10"/><text class="t1" x="22" y="{y+25}">Creative memory</text><text class="t2" x="22" y="{y+46}">24 notes, bge-small</text><text class="t3" x="22" y="{y+64}">feeds step 2, redo above 0.78</text>'
svg += f'<rect class="box led" x="235" y="{y}" width="215" height="76" rx="10"/><text class="t1" x="247" y="{y+25}">Cost ledger</text><text class="t2" x="247" y="{y+46}">logs every model call</text><text class="t3" x="247" y="{y+64}">stops at the USD cap</text>'
svg += '</svg>'

html_out = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ad Creative Agent</title>
<meta name="description" content="Agentic pipeline from launch brief to scored ad concepts. Fictional game, synthetic data, personal project.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@500;700&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#fbf7ef;--fg:#1b1d3a;--mut:#5d5f7a;--card:#fff;--line:#e3dccb;--acc:#c2410c;--llm:#fde7c2;--code:#dbeafe;--memc:#fbd5dc;--ledc:#d9f2df}}
@media(prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#12142e;--fg:#f1ead9;--mut:#aeb0cc;--card:#1b1e42;--line:#33376b;--acc:#ffb547;--llm:#4a3a1c;--code:#1f3358;--memc:#4a2233;--ledc:#1d4030}}}}
:root[data-theme=dark]{{--bg:#12142e;--fg:#f1ead9;--mut:#aeb0cc;--card:#1b1e42;--line:#33376b;--acc:#ffb547;--llm:#4a3a1c;--code:#1f3358;--memc:#4a2233;--ledc:#1d4030}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 Inter,system-ui,sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:24px 16px 64px}}h1,h2,h3{{font-family:Fredoka,Inter,sans-serif;line-height:1.2}}
h1{{font-size:clamp(2rem,6vw,3.2rem);margin:.2em 0}}h2{{margin-top:2.4em;font-size:1.6rem}}.mut{{color:var(--mut)}}
.tag{{display:inline-block;border:1px solid var(--line);background:var(--card);border-radius:99px;padding:2px 12px;font-size:.85rem;margin:0 6px 6px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;min-width:0}}.card img{{width:100%;height:auto;border-radius:10px;display:block}}
.card h3{{margin:.6em 0 .2em;font-size:1.1rem}}dl{{margin:0}}dt{{font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);margin-top:.5em}}dd{{margin:0;overflow-wrap:anywhere}}.why{{font-size:.88rem}}
.tw{{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--card)}}table{{border-collapse:collapse;width:100%;font-size:.9rem}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}th{{color:var(--mut);font-weight:600}}
svg{{width:100%;max-width:520px;height:auto;display:block;margin:0 auto}}.box{{stroke:var(--line);stroke-width:1.5}}.llm{{fill:var(--llm)}}.code{{fill:var(--code)}}.mem{{fill:var(--memc)}}.led{{fill:var(--ledc)}}
.t1{{font:700 19px Fredoka,sans-serif;fill:var(--fg)}}.t2{{font:600 14.5px Inter,sans-serif;fill:var(--fg)}}.t3{{font:13px Inter,sans-serif;fill:var(--mut)}}
.lead{{font-size:1.2rem;font-weight:600;margin:.2em 0 .8em}}.gap{{margin:0 0 1em}}.ph{{font-size:.78rem;color:var(--mut);margin:.4em 0 0}}
.note{{border-left:4px solid var(--acc);padding:4px 14px;background:var(--card);border-radius:0 10px 10px 0}}

</style></head><body><main>
<p><span class="tag">Personal project</span><span class="tag">Synthetic data</span><span class="tag">Fictional game</span></p>
<h1>Ad Creative Agent</h1>
<p class="lead">A copy, evaluation and judging pipeline for ad creative. Six real images from ChatGPT, made by hand, are scored by the vision critic. The API image adapter has not run live.</p>
<p class="note gap"><b>Image status.</b> The 6 real images further down came from ChatGPT (GPT image), run by hand through the web app on 2026-10-24, one chat per concept. The pipeline did not call an image API: the OpenAI adapter in the repo still has not run live, because the only API key returned 401. No local diffusion server answered on ports 7860 or 8188. The images in the Lantern Drift run below are still placeholders: typography plus procedural SVG art, drawn in headless Chrome. Adapters for Automatic1111 and ComfyUI are tested only against hand-built response fixtures. No video model has run.</p>
<p class="mut">One launch brief in. Nine scored ad concepts out, with copy for three platforms, an image each, and a reason for every pick. The game, Lantern Drift, is invented for this demo. Outputs below are real runs from {date}.</p>

<h2>How it works</h2>
<p>An explicit state machine. Blue steps are plain code. Amber steps call a model. The model name on each box comes from the run manifest.</p>
{svg}

<h2>Real GPT images: Tidebreak top 6 (made by hand in ChatGPT)</h2>
<p class="note">Concepts and art prompts come from run {e(tb['run_id'])}. Each prompt went into a new ChatGPT chat with the extra words "square 1:1 mobile game ad, no real brand names, the game is fictional, no text in the image". Images are 1254 by 1254. Because no text was drawn, the headline and CTA are not in the image, so the critic gate that compares text in the image with the intended text compares nothing. The critic is {e(gpt['model'])}, the same family as the writer. Cost of the six critic calls: ${gpt['cost_usd']}. Six images, one pass each, no retries, so this says nothing about how often GPT image misses a prompt.</p>
<div class="grid">{gpt_cards}</div>
<div class="tw"><table><tr><th>Concept</th><th>SVG placeholder: L / B / P / M</th><th>GPT image: L / B / P / M</th><th>Gate failures (GPT)</th></tr>{gpt_rows}</table></div>
<p class="mut">L legibility, B brand fit, P policy safety, M message match. The two columns are not a fair contest: the SVG images carry text and the GPT images do not, so legibility and message match mean different things. File: <code>results/vision_real_gpt.json</code>.</p>

<h2>Lantern Drift top 6 of 9 concepts (placeholder SVG images)</h2>
<p class="note">Run {e(man['run_id'])}, {date}. Models: {e(models)}. <b>Image backend: {e(man['image_backend']['name'])}.</b> No personal image API key and no diffusion server were reachable, so the images are typography plus procedural SVG rendered in headless Chrome. They are placeholders for the diffusion step, not diffusion output. The vision critic scores them as flat vector art, and says so.</p>
<div class="grid">{cards}</div>
<p class="mut">This run: {man['cost']['calls']} calls, {man['cost']['tokens_in']:,} input and {man['cost']['tokens_out']:,} output tokens, ${man['cost']['usd']} at the assumed prices in the repo. Scores: 0.25 legibility, 0.25 brand fit, 0.35 policy safety, 0.15 message match.</p>
<div class="tw"><table><tr><th>Step</th><th>Time</th><th>Cost</th></tr>{tr}</table></div>

<h2>Motion step</h2>
<p>A 6.5 s clip built by ffmpeg from the top 3 images: slow zoom and crossfade. No video model ran. It shows the slot for video, not video generation.</p>
<video controls muted playsinline preload="metadata" width="540" style="max-width:100%;height:auto;border-radius:12px"><source src="assets/motion.mp4" type="video/mp4"></video>

<h2>Creative memory</h2>
<p>24 invented past concept notes sit in a local vector index (bge-small, run on CPU). Before the angle agent writes, the six closest notes are put in its prompt as angles to avoid. After it writes, every new angle is embedded and compared to all notes. Above cosine 0.78, the agent redoes those angles once. Three trials per arm, same brief, {mem['trials']} runs each:</p>
<div class="tw"><table><tr><th>Arm</th><th>Mean of max similarity (after final draft)</th><th>Mean similarity</th><th>Angles over 0.78 after final draft</th><th>Trials that needed a redo</th></tr>
<tr><td>Memory off</td><td>{off[0]}</td><td>{off[1]}</td><td>{off[2]}</td><td>{off[3]}</td></tr><tr><td>Memory on</td><td>{on[0]}</td><td>{on[1]}</td><td>{on[2]}</td><td>{on[3]}</td></tr></table></div>
<p class="mut">Source: results/memory_demo.json. Three trials is a small sample. The 0.78 threshold was chosen after seeing the memory-off arm, on the same brief. The direction is clear, the size of the effect is not tight.</p>

<h2>Vision critic against seeded defects</h2>
<p>Sixteen images made on purpose: 15 with a known defect and 1 clean control. Defects: {vsum['by_category']['typo']['total']} typos in the drawn text, {vsum['by_category']['contrast']['total']} low-contrast text, {vsum['by_category']['claim']['total']} misleading or banned claims, {vsum['by_category']['aspect']['total']} wrong aspect ratios. Caught {vsum['caught']} of {vsum['defects']} ({round(vsum['detection_rate']*100)}%). Controls flagged: {vsum['controls_flagged']} of {vsum['controls']}. The model ({e(vs['model'])}) catches typos, claims and contrast. Plain code catches the aspect ratio, so those three do not test the model. I made the defects and I knew where they were, so this is an easy test. One control is too few to say anything about false alarms. An Opus run on the same 16 images was skipped: it would have broken the USD 6 cap.</p>
<div class="grid">{seeded}</div>

<h2>Copy evals: 12 fictional briefs</h2>
<p>Copy-only mode. A claude-opus-5-5 judge scores each brief's 9 concepts on four dimensions, 0 to 10. Deterministic checks run separately. Raw limit violations are counted before the repair step.</p>
<div class="tw"><table><tr><th>Brief (fictional)</th><th>Hook</th><th>Clarity</th><th>Policy safety</th><th>Platform fit</th><th>Raw limit violations</th><th>Concepts with banned claim</th><th>Cost</th></tr>{rows}</table></div>
<p>Across {S['briefs']} briefs and {S['concepts_total']} concepts: judge mean {S['judge_mean_over_briefs']}, {S['raw_limit_violations_total']} raw limit violations ({S['concepts_with_raw_violation_total']} of {S['concepts_total']} concepts needed repair), {S['final_limit_violations_total']} after repair, {S['banned_claim_concepts_total']} concepts with a banned claim. Total about ${S['total_cost_usd']}, mean ${S['mean_cost_per_brief_usd']} per brief (pipeline plus judge).</p>

<h2>Judge calibration</h2>
<p class="note gap"><b>The judge is unvalidated against humans.</b> Its platform-fit score is unreliable. All headline checks on this page are self-built tests with small n.</p>
<p>Ten hand-written copy sets for Lantern Drift: five good, five with one planted flaw each (w1 plants two weak dimensions). The judge scored them in two passes with different order. It found the planted flaw in {cal['weak_flaw_found']} weak sets, scored all dimensions at 6 or more in {cal['strong_all_dims_ge6']} strong sets, and averaged {cal['mean_strong']} on strong against {cal['mean_weak']} on weak. Mean score change between passes: {cal['order_sensitivity_mean_abs_diff']} points.</p>
<div class="tw"><table><tr><th>Item</th><th>Kind</th><th>Planted flaw</th><th>Hook</th><th>Clarity</th><th>Policy</th><th>Platform</th></tr>{calrows}</table></div>

<h2>Length-limit repair on a real call</h2>
<p>All 108 eval concepts passed the real limits first time, so the repair path never ran in the eval. To run it once on a live call, real copy from the Lantern Drift run was checked against deliberately tiny limits (Meta headline 16, text 40; TikTok and Google headline 14, text 30). Result: {rl['stats']['raw_violations']} raw violations, repaired by {e(str(rl['stats']['repaired_by']))}, {rl['stats']['final_violations']} left. One call, ${rl['cost_usd']}. Source: results/repair_live.json.</p>

<h2>Judge check</h2>
<p>Human check: <code>data/hand_score_sheet.csv</code> has 20 blind items. They were scored by Claude at the owner's request, not by a human, without seeing the judge's scores. Spearman vs the judge (n=20): hook strength 0.733, platform fit -0.141 (<code>results/hand_score.json</code>). The Opus re-score (<code>python -m adcreative judge-check</code>) did not run: about $0.09 of budget was left. No Opus agreement number. The pipeline's own images stay placeholders; the 6 hand-made GPT images are scored separately.</p>

<h2>Cost</h2>
<p>All live runs for this project, including failed attempts, cost ${total} by the repo's assumed prices (cap: $6). Per-call log: results/cost_log.jsonl.</p>
<p class="mut">Fictional game, synthetic data, no client material. Dates and models are from the run files. Code, tests, <a href="PRODUCT.md">PRODUCT.md</a> and <a href="INTERVIEW.md">INTERVIEW.md</a> are in the repository.</p>
</main></body></html>"""
shutil.copy(run_dir / "motion.mp4", D / "assets" / "motion.mp4")
(D / "index.html").write_text(html_out)
print("built", len(html_out), "bytes; ledger", total)
