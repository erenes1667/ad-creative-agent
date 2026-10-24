"""The agents. Each is one prompt plus a validator. All LLM access goes through the LLM wrapper."""
import json, re
from .checks import PLATFORMS, check_limits, trim_to_limit, banned_hits, copy_text, overlay_matches, aspect_ok
from .memory import SIM_THRESHOLD

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
FICTION = "All products here are fictional and invented for a portfolio demo. Never reference real brands."


# ---------- 1. brief parser ----------
def _v_brief(b):
    for k in ("name", "category", "pitch", "mechanics", "art_style", "tone", "palette", "style_tokens", "facts", "not_true"):
        if k not in b:
            raise ValueError(f"missing {k}")
    if len(b["palette"]) != 4 or not all(HEX.match(c) for c in b["palette"]):
        raise ValueError("palette must be 4 hex colors #RRGGBB: background, accent, light, pop")


def parse_brief(llm, raw: str) -> dict:
    sys = f"You turn a launch brief into JSON. {FICTION} Reply with JSON only."
    user = f"""Brief:
{raw}

Return JSON with keys: name, category, pitch (one sentence), mechanics (list), art_style, tone,
palette (4 hex colors: background dark, accent, light, pop; use colors named in the brief, else derive from the art style),
style_tokens (3 to 6 short visual phrases a designer would repeat), facts (true claims the brief supports),
not_true (things the brief says the product does NOT have or do; add obvious ones such as real-money rewards if absent),
launch_goal."""
    return llm.json("parse", sys, user, _v_brief, max_tokens=900, tag="parse")


# ---------- 2. audience + angle agent (with creative memory) ----------
def _v_angles(a):
    auds = a["audiences"]
    if len(auds) != 3 or any(len(x["hooks"]) != 3 for x in auds):
        raise ValueError("need exactly 3 audiences with exactly 3 hooks each")
    for x in auds:
        for h in x["hooks"]:
            h["angle"], h["hook_line"]


def angle_text(aud, h):
    return f"{aud['name']}: {h['angle']}. {h['hook_line']}"


def angles(llm, brief, memory, threshold=SIM_THRESHOLD, use_memory=True):
    q = f"{brief['name']} {brief['category']} {brief['pitch']}"
    past = memory.retrieve(q, k=6) if (use_memory and memory) else []
    avoid = "\n".join(f"- [{n['id']}] {n['audience']}: {n['angle']} ({n['hook']})" for n, _ in past) or "(none)"
    sys = f"You are a mobile performance-marketing strategist. {FICTION} Reply with JSON only."
    base = f"""Product brief (JSON):
{json.dumps({k: brief[k] for k in ('name','category','pitch','mechanics','tone','facts','not_true')})}

Past concepts already used. Do NOT repeat these angles or close paraphrases:
{avoid}

Return JSON: {{"audiences":[{{"name","description","hooks":[{{"angle":"the idea in one sentence","hook_line":"the first line a viewer sees, under 10 words"}} x3]}} x3]}}.
3 audiences, 3 hooks each. Audiences must differ in motivation, not only age. Hooks must be true to the facts."""
    report = {"retrieved": [{"id": n["id"], "sim": round(s, 3)} for n, s in past], "rounds": 1}
    out = llm.json("angles", sys, base, _v_angles, max_tokens=1800, tag="angles")

    def worst(o):
        rows = []
        for a in o["audiences"]:
            for h in a["hooks"]:
                s, nid = memory.max_sim(angle_text(a, h)) if memory else (0.0, None)
                rows.append((s, nid, a["name"], h["angle"]))
        return rows

    rows = worst(out)
    report["max_sim_first"] = round(max(r[0] for r in rows), 3)
    bad = [r for r in rows if r[0] > threshold]
    if bad and use_memory and memory:
        lst = "\n".join(f"- {r[2]}: {r[3]} (too close to {r[1]})" for r in bad)
        out = llm.json("angles", sys, base + f"\n\nThese angles in your last draft repeat past work. Replace them with new ones and keep the rest:\n{lst}\nPrevious draft:\n{json.dumps(out)}", _v_angles, max_tokens=1800, tag="angles-retry")
        rows = worst(out)
        report["rounds"] = 2
    report["max_sim_final"] = round(max(r[0] for r in rows), 3)
    report["over_threshold_final"] = sum(r[0] > threshold for r in rows)
    report["threshold"] = threshold
    return out, report


# ---------- 3. copy agent, limits enforced in code ----------
def _v_copy(c):
    if len(c["concepts"]) != 3:
        raise ValueError("need 3 concepts")
    for x in c["concepts"]:
        if set(x["copy"]) != set(PLATFORMS):
            raise ValueError("each concept needs meta, tiktok, google_uac")


def brand_note(brand):
    if not brand:
        return ""
    return f"\nBrand kit: voice = {brand['voice']}. Never use these phrases: {brand['banned_phrases']}."


def brand_hits(brand, text):
    return [f"brand: {w}" for w in (brand or {}).get("banned_phrases", []) if w.lower() in text.lower()]


def write_copy(llm, brief, aud, brand=None):
    lim = {p: {"headline_max": v["headline"], "text_max": v["text"], "cta_one_of": v["ctas"]} for p, v in PLATFORMS.items()}
    sys = f"You are a direct-response copywriter for mobile ads. {FICTION} Plain words, no hype, no emoji, no em dashes. Reply with JSON only."
    user = f"""Product: {json.dumps({k: brief[k] for k in ('name','pitch','mechanics','tone','facts','not_true')})}
Audience: {aud['name']} - {aud['description']}
Hooks (one concept each, same order):
{json.dumps(aud['hooks'])}

Platform limits in characters (hard): {json.dumps(lim)}
Never claim anything in not_true. No invented statistics, rankings or guarantees.{brand_note(brand)}
Return JSON: {{"concepts":[{{"copy":{{"meta":{{"headline","text","cta"}},"tiktok":{{...}},"google_uac":{{...}}}}}} x3]}}"""
    return llm.json("copy", sys, user, _v_copy, max_tokens=2200, tag="copy")["concepts"]


def enforce_limits(llm, copy: dict) -> tuple[dict, dict]:
    """Validate, one cheap repair call, then deterministic trim. Returns fixed copy and stats."""
    raw = {p: check_limits(p, copy[p]) for p in PLATFORMS}
    n_raw = sum(len(v) for v in raw.values())
    stats = {"raw_violations": n_raw, "repaired_by": None}
    if n_raw == 0:
        return copy, stats
    msgs = [e for v in raw.values() for e in v]
    fixed = copy
    try:
        fixed = llm.json("repair", "Shorten ad copy to fit limits. Keep meaning. JSON only.",
                         f"Copy: {json.dumps(copy)}\nProblems: {msgs}\nLimits: {json.dumps(PLATFORMS)}\nReturn the full corrected JSON object with keys meta, tiktok, google_uac.",
                         lambda o: [o[p] for p in PLATFORMS], max_tokens=700, tag="repair")
    except ValueError:
        pass
    llm_ok = fixed is not copy and all(not check_limits(p, fixed[p]) for p in PLATFORMS)
    stats["repaired_by"] = "llm" if llm_ok else "trim"
    out = {}
    for p, lim in PLATFORMS.items():
        it = dict(fixed.get(p) or copy[p])
        it["headline"] = trim_to_limit(str(it.get("headline", "")), lim["headline"])
        it["text"] = trim_to_limit(str(it.get("text", "")), lim["text"])
        if it.get("cta") not in lim["ctas"]:
            it["cta"] = lim["ctas"][0]
        out[p] = it
    stats["final_violations"] = sum(len(check_limits(p, out[p])) for p in PLATFORMS)
    return out, stats


# ---------- 4. art director ----------
def _v_art(a):
    if len(a["concepts"]) != 3:
        raise ValueError("need 3 concepts")
    for x in a["concepts"]:
        t = x["overlay_text"]
        if len(t) > 28 or len(t.split()) > 5:
            raise ValueError(f"overlay_text too long: {t!r} (max 28 chars, 5 words)")
        if x["layout"] not in ("top", "bottom"):
            raise ValueError("layout must be top or bottom")


def art_direct(llm, brief, aud, concepts):
    from .render import MOTIFS
    sys = f"You are an art director for mobile ads. {FICTION} Reply with JSON only."
    user = f"""Product art style: {brief['art_style']}
Style tokens (must shape every prompt): {brief['style_tokens']}
Palette: {brief['palette']}
Never depict: {brief['not_true']}
Concepts for audience "{aud['name']}":
{json.dumps([{'angle': c['angle'], 'hook_line': c['hook_line'], 'meta_headline': c['copy']['meta']['headline']} for c in concepts])}

For each concept return: image_prompt (one paragraph for an image model, no text rendering instructions),
motif (one of {MOTIFS}, pick the one that fits the idea; vary across the three),
layout ("top" or "bottom"), overlay_text (the words drawn on the image: max 5 words, max 28 characters, no punctuation tricks).
Return JSON: {{"concepts":[{{"image_prompt","motif","layout","overlay_text"}} x3]}}"""
    out = llm.json("art", sys, user, _v_art, max_tokens=1500, tag="art")["concepts"]
    for a in out:  # style tokens are appended in code so they can never be dropped
        a["image_prompt"] = a["image_prompt"].rstrip() + " Style tokens: " + "; ".join(brief["style_tokens"]) + "."
    return out


# ---------- 6. vision critic ----------
CRITIC_RUBRIC = """Score 0-10 (10 is best):
legibility: can every word be read at phone size, is contrast adequate, is the CTA clear.
brand_fit: does it match the art style and palette given.
policy_safety: 10 = no ad-policy risk. Deduct for misleading gameplay (showing mechanics the product does not have),
 real-money or prize implications, fake UI such as fake buttons or fake notifications, unsourced stats, shouting.
message_match: does the image support the copy headline without contradicting it."""


def _v_critic(c):
    for k in ("text_read", "legibility", "brand_fit", "policy_safety", "message_match", "summary"):
        c[k]
    for k in ("legibility", "brand_fit", "policy_safety", "message_match"):
        if not 0 <= float(c[k]) <= 10:
            raise ValueError(f"{k} out of range")


def critique(llm, brief, concept, image_path, role="critic"):
    sys = "You review ad images as a strict creative reviewer. Fictional demo product. JSON only."
    user = f"""Product: {brief['name']}. Art style: {brief['art_style']}. Palette: {brief['palette']}.
True facts: {brief['facts']}
NOT true (must not be implied): {brief['not_true']}
Ad headline that will run with this image: {concept['copy']['meta']['headline']}

{CRITIC_RUBRIC}
Also copy out, exactly as you see it, every word of text visible in the image (text_read).
Return JSON: {{"text_read","legibility","brand_fit","policy_safety","message_match","policy_notes","summary":"one sentence"}}"""
    c = llm.json(role, sys, user, _v_critic, images=[image_path], max_tokens=500, tag=role)
    from PIL import Image
    with Image.open(image_path) as im:
        c["aspect_ok"] = aspect_ok(*im.size)
    intended = f"{concept['art']['overlay_text']} {concept['art']['cta_label']}"
    c["text_matches_intended"] = overlay_matches(intended, c["text_read"])
    c["intended_text"] = intended
    return c


# ---------- 7. ranker (deterministic) ----------
WEIGHTS = {"legibility": 0.25, "brand_fit": 0.25, "policy_safety": 0.35, "message_match": 0.15}
MIN_POLICY = 6.0
MIN_LEGIBILITY = 5.0


def score(c):
    return round(sum(float(c["critic"][k]) * w for k, w in WEIGHTS.items()), 3)


def gate_failures(c):
    f = []
    if c["checks"]["banned"]:
        f.append("banned claim in copy: " + ", ".join(c["checks"]["banned"]))
    if c["checks"].get("limit_final_violations"):
        f.append("copy over platform limit")
    if float(c["critic"]["policy_safety"]) < MIN_POLICY:
        f.append(f"policy_safety {c['critic']['policy_safety']} below {MIN_POLICY}")
    if float(c["critic"]["legibility"]) < MIN_LEGIBILITY:
        f.append(f"legibility {c['critic']['legibility']} below {MIN_LEGIBILITY}")
    if not c["critic"].get("aspect_ok", True):
        f.append("image is not 1:1")
    if not c["critic"]["text_matches_intended"]:
        f.append("text in image differs from intended text (possible typo)")
    return f


def rank(concepts, k=6, per_audience=2):
    for c in concepts:
        c["score"] = score(c)
        c["gate_failures"] = gate_failures(c)
    ok = sorted([c for c in concepts if not c["gate_failures"]], key=lambda c: -c["score"])
    top, per = [], {}
    for c in ok:
        if per.get(c["audience"], 0) >= per_audience:
            continue
        per[c["audience"]] = per.get(c["audience"], 0) + 1
        top.append(c)
        if len(top) == k:
            break
    out = []
    for i, c in enumerate(top, 1):
        best = max(WEIGHTS, key=lambda k_: float(c["critic"][k_]))
        out.append({"id": c["id"], "rank": i, "score": c["score"],
                    "reason": f"Score {c['score']}. Strongest on {best} ({c['critic'][best]}). {c['critic']['summary']} Audience: {c['audience']}."})
    return out
