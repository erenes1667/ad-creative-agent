import json
from pathlib import Path
from PIL import Image
from adcreative import images, pipeline
from adcreative.checks import validate_manifest
from adcreative.memory import Memory
from conftest import FakeLLM, fake_embed


def test_backend_falls_back_when_nothing_available(tmp_path):
    env = tmp_path / ".env"; env.write_text("OPENAI_API" + "_KEY=abc\n")
    b = images.detect_backend(str(env), reachable=lambda u: False)
    assert b["name"] == "svg-fallback"  # the employer-style OPENAI_API_KEY name is never used


def test_backend_prefers_personal_openai_then_server(tmp_path):
    env = tmp_path / ".env"; env.write_text("OPENAI_API_KEY_PERSONAL=abc\n")
    assert images.detect_backend(str(env), reachable=lambda u: True)["name"] == "openai"
    env.write_text("")
    assert images.detect_backend(str(env), reachable=lambda u: "7860" in u)["url"].endswith(":7860")


def test_copy_mode_end_to_end(tmp_path):
    man, out = pipeline.run("raw", FakeLLM(), mode="copy", out_dir=tmp_path / "r", memory=Memory([], embedder=fake_embed))
    validate_manifest(man)
    assert len(man["concepts"]) == 9 and man["top"] == []
    assert (out / "manifest.json").exists() and "All concepts" in (out / "contact_sheet.html").read_text()


def test_full_mode_end_to_end_with_stub_images(tmp_path, monkeypatch):
    def stub(backend, art, overlay, palette, seed, out_png):
        out_png.parent.mkdir(parents=True, exist_ok=True); Image.new("RGB", (16, 16)).save(out_png); return out_png
    monkeypatch.setattr(pipeline, "generate", stub)
    man, out = pipeline.run("raw", FakeLLM(), mode="full", out_dir=tmp_path / "r", memory=Memory([], embedder=fake_embed),
                            backend={"name": "svg-fallback", "detail": "test"})
    validate_manifest(man)
    assert len(man["top"]) == 6 and len({t["id"] for t in man["top"]}) == 6
    assert all(c["art"]["cta_label"] == c["copy"]["meta"]["cta"] for c in man["concepts"])
    assert [s["step"] for s in man["trace"]] == ["parse", "angles", "copy", "art", "images", "critic", "rank"]
    assert "Top picks" in (out / "contact_sheet.html").read_text()
    assert json.loads((out / "manifest.json").read_text())["fictional"] is True


FIX = Path(__file__).parent / "fixtures"


class _Resp:
    def __init__(self, b): self.b = b
    def read(self): return self.b


def _router(routes, seen):
    def fake(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        seen.append((url, None if isinstance(req, str) else json.loads(req.data)))
        for k, v in routes.items():
            if k in url:
                return _Resp(v)
        raise AssertionError(f"unexpected url {url}")
    return fake


def test_a1111_adapter_with_response_fixture(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(images.urllib.request, "urlopen", _router({"/sdapi/v1/txt2img": (FIX / "a1111_txt2img_response.json").read_bytes()}, seen))
    out = tmp_path / "a.png"
    images.diffusion_generate("http://localhost:7860", "a lantern", out, seed=5)
    assert out.read_bytes() == (FIX / "tiny.png").read_bytes()
    url, body = seen[0]
    assert url == "http://localhost:7860/sdapi/v1/txt2img" and body["prompt"] == "a lantern" and body["seed"] == 5 and body["width"] == 1024
    assert "text" in body["negative_prompt"]


def test_comfy_adapter_with_response_fixtures(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(images.urllib.request, "urlopen", _router({
        "/prompt": (FIX / "comfy_prompt_response.json").read_bytes(),
        "/history/abc-123": (FIX / "comfy_history_response.json").read_bytes(),
        "/view": (FIX / "tiny.png").read_bytes()}, seen))
    out = tmp_path / "c.png"
    images.diffusion_generate("http://localhost:8188", "a lantern", out, seed=3)
    assert out.read_bytes() == (FIX / "tiny.png").read_bytes()
    wf = seen[0][1]["prompt"]
    assert wf["6"]["inputs"]["text"] == "a lantern" and wf["3"]["inputs"]["seed"] == 3 and wf["9"]["class_type"] == "SaveImage"
    assert "filename=adcreative_00001_.png" in seen[-1][0]


def test_diffusion_output_gets_text_panel_composited(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(images.urllib.request, "urlopen", _router({"/sdapi/v1/txt2img": (FIX / "a1111_txt2img_response.json").read_bytes()}, seen))
    html = {}
    monkeypatch.setattr(images, "render_svg_ad", lambda spec, pal, seed, out: html.update(spec=spec) or out)
    art = {"image_prompt": "x", "overlay_text": "Light the way", "cta_label": "Play Now", "motif": "burst", "layout": "top"}
    images.generate({"name": "diffusion-server", "url": "http://localhost:7860"}, art, {}, ["#000000"] * 4, 1, tmp_path / "a.png")
    assert html["spec"]["bg_image"].startswith("data:image/png;base64,") and html["spec"]["overlay_text"] == "Light the way"
    from adcreative.render import compose_html
    assert "<image href=\"data:image/png" in compose_html(html["spec"], ["#1B1F4B", "#FFB547", "#FFF1D6", "#E8556D"], 1)


def test_brand_kit_flows_into_prompt_and_checks(tmp_path):
    kit = json.loads((Path(__file__).parent.parent / "data" / "brands" / "lantern-voice.json").read_text())
    seen = []

    class Spy(FakeLLM):
        def json(self, role, system, user, *a, **k):
            seen.append(user)
            return super().json(role, system, user, *a, **k)

    man, _ = pipeline.run("raw", Spy(), mode="copy", out_dir=tmp_path / "r", memory=Memory([], embedder=fake_embed), brand=kit)
    assert len(man["concepts"]) == 9
    assert any("calm, warm" in u for u in seen)
    from adcreative import agents
    assert agents.brand_hits(kit, "An addictive puzzle") == ["brand: addictive"]
    assert agents.brand_hits(None, "anything") == []
