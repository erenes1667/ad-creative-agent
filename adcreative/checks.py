"""Deterministic checks: platform length limits, banned claims, manifest schema, overlay-text match."""
import re

# House limits, deliberately conservative. Real limits vary by placement; edit here.
PLATFORMS = {
    "meta": {"headline": 40, "text": 125, "ctas": ["Play Now", "Install Now", "Learn More", "Get Offer"]},
    "tiktok": {"headline": 30, "text": 100, "ctas": ["Play Now", "Install Now", "Learn More", "Download Now"]},
    "google_uac": {"headline": 30, "text": 90, "ctas": ["Install", "Play", "Learn More"]},
}

BANNED = [
    (r"\bguarantee[sd]?\b", "guarantee"),
    (r"#\s?1\b|\bnumber one\b", "ranking claim"),
    (r"\bbest\s+(\w+\s+)?(game|app)\s+(ever|in the world)\b", "superlative claim"),
    (r"\b(win|earn)\s+(real\s+)?(cash|money|prizes?)\b", "real-money claim"),
    (r"\bfree\s+money\b", "real-money claim"),
    (r"\b\d{2,3}\s?%\s+(of\s+)?(players|people|users|gamers)\b", "unsourced statistic"),
    (r"\baddict(ive|ion)\b", "addiction framing"),
    (r"\bclinically\b|\bcures?\b", "health claim"),
    (r"!!+", "excess punctuation"),
]


def check_limits(platform: str, item: dict) -> list[str]:
    lim, errs = PLATFORMS[platform], []
    for field in ("headline", "text"):
        v = item.get(field)
        if not isinstance(v, str) or not v.strip():
            errs.append(f"{platform}.{field} missing")
        elif len(v) > lim[field]:
            errs.append(f"{platform}.{field} is {len(v)} chars, limit {lim[field]}")
    if item.get("cta") not in lim["ctas"]:
        errs.append(f"{platform}.cta {item.get('cta')!r} not in {lim['ctas']}")
    return errs


def trim_to_limit(s: str, n: int) -> str:
    """Last-resort deterministic fix: cut at a word boundary, drop trailing punctuation."""
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0] if " " in s[:n] else s[:n]
    return cut.rstrip(" ,;:-")


def banned_hits(text: str) -> list[str]:
    hits = [label for pat, label in BANNED if re.search(pat, text, re.I)]
    if len(re.findall(r"\b[A-Z]{4,}\b", text)) > 2:
        hits.append("shouting caps")
    return hits


def copy_text(copy: dict) -> str:
    return " ".join(f"{v.get('headline','')} {v.get('text','')}" for v in copy.values())


def _words(s: str) -> list[str]:
    return sorted(re.findall(r"[a-z0-9']+", s.lower()))


def overlay_matches(intended: str, read_by_critic: str) -> bool:
    """True when the words the critic read in the image equal the words we meant to draw."""
    return _words(intended) == _words(read_by_critic)


MANIFEST_KEYS = {"version", "run_id", "generated_at", "fictional", "mode", "image_backend",
                 "models", "brief", "concepts", "top", "cost"}
CONCEPT_KEYS = {"id", "audience", "angle", "hook_line", "copy", "checks"}


def validate_manifest(m: dict) -> None:
    miss = MANIFEST_KEYS - m.keys()
    if miss:
        raise ValueError(f"manifest missing keys: {sorted(miss)}")
    if m["fictional"] is not True:
        raise ValueError("manifest must be labeled fictional")
    if m["mode"] not in ("copy", "full"):
        raise ValueError("mode must be copy or full")
    ids = set()
    for c in m["concepts"]:
        miss = CONCEPT_KEYS - c.keys()
        if miss:
            raise ValueError(f"concept {c.get('id')} missing {sorted(miss)}")
        if set(c["copy"]) - set(PLATFORMS):
            raise ValueError(f"concept {c['id']} has unknown platform")
        for p, item in c["copy"].items():
            errs = check_limits(p, item)
            if errs:
                raise ValueError(f"concept {c['id']}: {errs[0]}")
        if m["mode"] == "full" and "image" not in c:
            raise ValueError(f"concept {c['id']} missing image in full mode")
        ids.add(c["id"])
    if len(ids) != len(m["concepts"]):
        raise ValueError("duplicate concept ids")
    if len(m["top"]) > 6 or any(t["id"] not in ids for t in m["top"]):
        raise ValueError("top must be <=6 known concept ids")
    if m["mode"] == "full" and not all(t.get("reason") for t in m["top"]):
        raise ValueError("every top entry needs a reason")


def aspect_ok(width: int, height: int, expected: float = 1.0, tol: float = 0.02) -> bool:
    """Deterministic image-shape check. Ads here are 1:1."""
    return abs(width / height - expected) <= tol * expected
