"""Thin Anthropic wrapper: personal key from env at run time, workspace header, cost ledger, spend cap."""
import base64, json, os, re, threading, time
from pathlib import Path

MODELS = {
    "parse": os.environ.get("AC_MODEL_PARSE", "claude-haiku-5-5"),
    "repair": os.environ.get("AC_MODEL_REPAIR", "claude-haiku-5-5"),
    "angles": os.environ.get("AC_MODEL_ANGLES", "claude-sonnet-5-5"),
    "copy": os.environ.get("AC_MODEL_COPY", "claude-sonnet-5-5"),
    "art": os.environ.get("AC_MODEL_ART", "claude-sonnet-5-5"),
    "critic": os.environ.get("AC_MODEL_CRITIC", "claude-sonnet-5-5"),
    "judge": os.environ.get("AC_MODEL_JUDGE", "claude-opus-5-5"),
    "critic_check": os.environ.get("AC_MODEL_CRITIC_CHECK", "claude-opus-5-5"),
    "judge_check": os.environ.get("AC_MODEL_JUDGE_CHECK", "claude-opus-5-5"),
}
# ASSUMED USD per million tokens (input, output). Deliberately on the high side so the
# spend cap is conservative. Check the Console for billed amounts.
PRICES = {
    "claude-haiku-5-5": (1.0, 5.0),
    "claude-sonnet-5-5": (3.0, 15.0),
    "claude-opus-5-5": (15.0, 75.0),
}
# These models think by default and thinking tokens count against max_tokens, so add headroom.
# Billed output tokens (thinking included) are what the ledger records.
THINK_HEADROOM = 6000
SPEND_CAP_USD = float(os.environ.get("AC_SPEND_CAP_USD", "6"))
LEDGER = Path(__file__).resolve().parent.parent / "results" / "cost_log.jsonl"
_lock = threading.Lock()


class CapExceeded(RuntimeError):
    pass


def ledger_total(path: Path = LEDGER) -> float:
    if not path.exists():
        return 0.0
    return sum(json.loads(l)["usd"] for l in path.read_text().splitlines() if l.strip())


def cost_usd(model: str, tin: int, tout: int) -> float:
    pi, po = PRICES[model]
    return (tin * pi + tout * po) / 1e6


def load_personal_env(path=".env"):
    """Read ONLY the two personal-key variables into os.environ. Never prints them."""
    want = ("ANTHROPIC_API_KEY_PERSONAL", "ANTHROPIC_WORKSPACE_ID_PERSONAL")
    if all(os.environ.get(k) for k in want):
        return
    if not Path(path).expanduser().exists():
        return
    for line in Path(path).expanduser().read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() in want:
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no JSON object in reply")
    return json.loads(text[i : j + 1])


def png_block(path, max_side=768):
    from PIL import Image
    import io
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.b64encode(buf.getvalue()).decode()}}


class LLM:
    def __init__(self, scope="run", ledger: Path = LEDGER, cap=SPEND_CAP_USD):
        import anthropic
        load_personal_env()
        env = os.environ
        if not (env.get("ANTHROPIC_API_KEY_PERSONAL") and env.get("ANTHROPIC_WORKSPACE_ID_PERSONAL")):
            raise SystemExit("Set ANTHROPIC_API_KEY_PERSONAL and ANTHROPIC_WORKSPACE_ID_PERSONAL (env or .env), see README Quickstart")
        self.client = anthropic.Anthropic(
            api_key=env["ANTHROPIC_API_KEY_PERSONAL"],
            default_headers={"anthropic-workspace-id": env["ANTHROPIC_WORKSPACE_ID_PERSONAL"]},
        )
        self.scope, self.ledger, self.cap = scope, Path(ledger), cap
        self.spent = 0.0
        self.tokens = {"in": 0, "out": 0}
        self.calls = 0

    def text(self, role, system, user, images=(), max_tokens=2000, tag=""):
        model = MODELS[role]
        with _lock:
            if ledger_total(self.ledger) >= self.cap:
                raise CapExceeded(f"spend cap {self.cap} USD reached")
        content = [png_block(p) for p in images] + [{"type": "text", "text": user}]
        r = self.client.messages.create(model=model, max_tokens=max_tokens + THINK_HEADROOM, system=system,
                                        messages=[{"role": "user", "content": content}])
        tin, tout = r.usage.input_tokens, r.usage.output_tokens
        usd = cost_usd(model, tin, tout)
        with _lock:
            self.ledger.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger.open("a") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "scope": self.scope,
                                    "role": role, "model": model, "tag": tag, "in": tin,
                                    "out": tout, "stop": r.stop_reason, "usd": round(usd, 6)}) + "\n")
        self.spent += usd
        self.tokens["in"] += tin
        self.tokens["out"] += tout
        self.calls += 1
        return "".join(b.text for b in r.content if b.type == "text")

    def json(self, role, system, user, validate=None, images=(), max_tokens=2000, tag=""):
        """JSON reply with one retry that feeds the parse/validation error back."""
        err = None
        for attempt in range(2):
            u = user if err is None else f"{user}\n\nYour previous reply was rejected: {err}\nReturn corrected JSON only."
            raw = self.text(role, system, u, images, max_tokens, tag)
            try:
                obj = extract_json(raw)
                if validate:
                    validate(obj)
                return obj
            except (ValueError, KeyError, TypeError) as e:
                err = str(e)
        raise ValueError(f"{tag}: invalid JSON after retry: {err}")
