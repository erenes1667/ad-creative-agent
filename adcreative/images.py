"""Image backend selection. Order: personal OpenAI key (name check only), local diffusion server, SVG fallback."""
import base64, json, os, urllib.parse, urllib.request
from pathlib import Path
from .render import MOTIFS, render_svg_ad

PROBES = os.environ.get("SD_URLS", "http://localhost:7860,http://localhost:8188").split(",")  # A1111 and ComfyUI default ports


def _reachable(url, timeout=3):
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


def detect_backend(env_file=".env", probes=PROBES, reachable=_reachable) -> dict:
    p = Path(env_file).expanduser()
    names = [l.split("=", 1)[0].strip() for l in p.read_text().splitlines() if "=" in l] if p.exists() else []
    if "OPENAI_API_KEY_PERSONAL" in names:
        return {"name": "openai", "model": "gpt-image-2.5-flare", "detail": "personal key present"}
    for u in probes:
        if reachable(u):
            return {"name": "diffusion-server", "url": u, "detail": "local diffusion server reachable"}
    return {"name": "svg-fallback", "detail": "no working OpenAI key, no local diffusion server"}


def _openai_generate(prompt, out_png: Path):  # written for the pluggable slot, NEVER RUN in this repo
    from .llm import load_personal_env  # noqa: F401  (key is read from env at run time only)
    key = os.environ["OPENAI_API_KEY_PERSONAL"]
    req = urllib.request.Request("https://api.openai.com/v1/images/generations",
        data=json.dumps({"model": "gpt-image-2.5-flare", "prompt": prompt, "size": "1024x1024"}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    b64 = json.load(urllib.request.urlopen(req, timeout=120))["data"][0]["b64_json"]
    out_png.write_bytes(base64.b64decode(b64))


def generate(backend: dict, art: dict, overlay: dict, palette, seed, out_png: Path) -> Path:
    """SVG fallback draws everything. Diffusion backends draw the picture only, then the same text panel
    and CTA are composited on top, because diffusion models cannot be trusted to spell."""
    if backend["name"] == "svg-fallback":
        return render_svg_ad({**art, **overlay}, palette, seed, out_png)
    raw = out_png.with_name(out_png.stem + "_raw.png")
    if backend["name"] == "openai":
        _openai_generate(art["image_prompt"], raw)
    elif backend["name"] == "diffusion-server":
        diffusion_generate(backend["url"], art["image_prompt"], raw, seed)
    else:
        raise ValueError(f"unknown backend {backend['name']}")
    uri = "data:image/png;base64," + base64.b64encode(raw.read_bytes()).decode()
    return render_svg_ad({**art, **overlay, "bg_image": uri}, palette, seed, out_png)


NEGATIVE = "text, letters, words, watermark, logo, realistic human face"
COMFY_CKPT = os.environ.get("COMFY_CKPT", "sd_xl_base_1.0.safetensors")  # set to a checkpoint your server has


def _post(url, payload, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def a1111_generate(url, prompt, out_png: Path, seed=-1):
    """Automatic1111 /sdapi/v1/txt2img. Request shape and response shape follow the A1111 API docs;
    tested offline against a response fixture, not yet against a live server."""
    body = json.loads(_post(url.rstrip("/") + "/sdapi/v1/txt2img",
        {"prompt": prompt, "negative_prompt": NEGATIVE, "width": 1024, "height": 1024, "steps": 25, "seed": seed}))
    img = body["images"][0].split(",", 1)[-1]  # some builds prefix a data URI
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_png.write_bytes(base64.b64decode(img))


def comfy_workflow(prompt, seed, ckpt=COMFY_CKPT, size=1024, steps=25):
    return {"3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": 7, "sampler_name": "euler", "scheduler": "normal",
                  "denoise": 1, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": size, "height": size, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["4", 1]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "adcreative"}}}


def comfy_generate(url, prompt, out_png: Path, seed=0, poll_s=2, max_wait_s=300):
    """ComfyUI: POST /prompt, poll /history/<id>, GET /view. Shapes follow the ComfyUI API; tested offline against
    recorded-shape fixtures only."""
    import time
    base = url.rstrip("/")
    pid = json.loads(_post(base + "/prompt", {"prompt": comfy_workflow(prompt, seed)}))["prompt_id"]
    t0 = time.time()
    while True:
        hist = json.loads(urllib.request.urlopen(f"{base}/history/{pid}", timeout=30).read())
        if pid in hist and hist[pid].get("outputs"):
            break
        if time.time() - t0 > max_wait_s:
            raise TimeoutError("ComfyUI job did not finish")
        time.sleep(poll_s)
    im = next(i for o in hist[pid]["outputs"].values() for i in o.get("images", []))
    q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""), "type": im.get("type", "output")})
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_png.write_bytes(urllib.request.urlopen(f"{base}/view?{q}", timeout=60).read())


def diffusion_generate(url, prompt, out_png: Path, seed=-1):
    """Pick the adapter from the port. 8188 is ComfyUI, everything else is treated as A1111."""
    (comfy_generate if ":8188" in url else a1111_generate)(url, prompt, out_png, max(seed, 0) if ":8188" in url else seed)
