import hashlib, numpy as np, pytest


def fake_embed(texts):
    out = []
    for t in texts:
        v = np.zeros(64)
        for w in t.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
        out.append(v / (np.linalg.norm(v) or 1))
    return np.array(out)


def good_copy(h="Light the lanterns"):
    return {"meta": {"headline": h, "text": "Rotate paper tiles to link the light.", "cta": "Play Now"},
            "tiktok": {"headline": h, "text": "Calm puzzle, no timers.", "cta": "Play Now"},
            "google_uac": {"headline": h, "text": "Free paper-tile puzzles.", "cta": "Install"}}


class FakeLLM:
    """Canned replies keyed by tag. Validators run, so schema bugs surface offline."""
    def __init__(self, over=None):
        self.spent, self.calls, self.tokens, self.log, self.over = 0.0, 0, {"in": 0, "out": 0}, [], over or {}

    def json(self, role, system, user, validate=None, images=(), max_tokens=0, tag=""):
        self.calls += 1
        self.log.append(tag)
        o = self.over.get(tag) or self.canned(tag)
        if validate:
            validate(o)
        return o

    def canned(self, tag):
        if tag == "parse":
            return {"name": "Lantern Drift", "category": "puzzle", "pitch": "p", "mechanics": ["rotate"], "art_style": "paper",
                    "tone": "calm", "palette": ["#1B1F4B", "#FFB547", "#FFF1D6", "#E8556D"], "style_tokens": ["paper-cut", "grain"],
                    "facts": ["free"], "not_true": ["real money"]}
        if tag.startswith("angles"):
            return {"audiences": [{"name": f"aud{i}", "description": "d", "hooks": [{"angle": f"angle {i}{j}", "hook_line": f"hook {i}{j}"} for j in range(3)]} for i in range(3)]}
        if tag == "copy":
            return {"concepts": [{"copy": good_copy(f"Headline {k}")} for k in range(3)]}
        if tag == "art":
            return {"concepts": [{"image_prompt": "a lantern", "motif": "burst", "layout": "top", "overlay_text": "Light the way"} for _ in range(3)]}
        if tag == "critic":
            return {"text_read": "Light the way Play Now", "legibility": 8, "brand_fit": 8, "policy_safety": 9, "message_match": 7, "summary": "Clear."}
        raise KeyError(tag)
