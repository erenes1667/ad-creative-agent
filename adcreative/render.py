"""Fallback image step: typography plus procedural SVG art, rasterised with headless Chrome.
This is NOT diffusion. It is a pluggable stand-in used when no image model is reachable."""
import html, random, shutil, subprocess, tempfile
from pathlib import Path

MOTIFS = ["tile_grid", "cascade", "orb_glow", "path_board", "burst"]
SIZE = 1080


def _lum(hex_):
    h = hex_.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ink_for(bg):
    return "#111111" if _lum(bg) > 0.4 else "#FFFFFF"


def _art(motif, pal, rnd):
    bg, acc, light, pop = pal
    o = []
    if motif == "tile_grid":
        n, s, g = 5, 150, 22
        x0 = (SIZE - (n * s + (n - 1) * g)) // 2
        for r in range(n):
            for c in range(n):
                x, y = x0 + c * (s + g), 70 + r * (s + g)
                lit = rnd.random() < 0.35
                o.append(f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="26" fill="{light if lit else acc}" opacity="{1 if lit else .55}"/>')
                a = rnd.choice([0, 90, 180, 270])
                o.append(f'<g transform="rotate({a} {x+s/2} {y+s/2})"><path d="M{x+s/2} {y+s/2} V{y+24} M{x+s/2} {y+s/2} H{x+s-24}" stroke="{pop if lit else light}" stroke-width="14" stroke-linecap="round" fill="none"/><circle cx="{x+s/2}" cy="{y+s/2}" r="16" fill="{pop}"/></g>')
    elif motif == "cascade":
        for col in range(9):
            x = 60 + col * 120
            for k in range(rnd.randint(3, 6)):
                y = rnd.randint(40, 760)
                r = rnd.randint(22, 52)
                o.append(f'<ellipse cx="{x}" cy="{y}" rx="{r*.8}" ry="{r}" fill="{rnd.choice([acc, light, pop])}" opacity="{rnd.choice([.5,.8,1])}"/>')
                o.append(f'<line x1="{x}" y1="{y+r}" x2="{x}" y2="{y+r+40}" stroke="{light}" stroke-width="3" opacity=".6"/>')
    elif motif == "orb_glow":
        o.append(f'<defs><radialGradient id="g"><stop offset="0" stop-color="{pop}"/><stop offset=".45" stop-color="{acc}" stop-opacity=".6"/><stop offset="1" stop-color="{bg}" stop-opacity="0"/></radialGradient></defs>')
        o.append(f'<circle cx="540" cy="400" r="480" fill="url(#g)"/>')
        for i, r in enumerate((90, 170, 250, 330)):
            o.append(f'<circle cx="540" cy="400" r="{r}" fill="none" stroke="{light}" stroke-width="5" stroke-dasharray="{14+i*10} {18}" opacity=".7"/>')
        for _ in range(14):
            o.append(f'<circle cx="{rnd.randint(80,1000)}" cy="{rnd.randint(60,720)}" r="{rnd.randint(8,22)}" fill="{light}" opacity=".85"/>')
    elif motif == "path_board":
        pts = [(100, 700)]
        for i in range(1, 8):
            pts.append((100 + i * 125, rnd.randint(140, 680)))
        d = "M" + " L".join(f"{x} {y}" for x, y in pts)
        o.append(f'<path d="{d}" stroke="{light}" stroke-width="34" stroke-linejoin="round" stroke-linecap="round" fill="none" opacity=".9"/>')
        o.append(f'<path d="{d}" stroke="{pop}" stroke-width="10" stroke-linejoin="round" stroke-linecap="round" fill="none" stroke-dasharray="4 26"/>')
        for x, y in pts:
            o.append(f'<circle cx="{x}" cy="{y}" r="38" fill="{acc}"/><circle cx="{x}" cy="{y}" r="16" fill="{pop}"/>')
    else:  # burst
        for i in range(24):
            a = i * 15
            o.append(f'<g transform="rotate({a} 540 400)"><polygon points="540,400 520,-80 560,-80" fill="{acc if i%2 else light}" opacity=".55"/></g>')
        for _ in range(9):
            x, y, s = rnd.randint(120, 960), rnd.randint(100, 700), rnd.randint(50, 110)
            o.append(f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="{s//4}" fill="{rnd.choice([pop, light, acc])}" transform="rotate({rnd.randint(-30,30)} {x} {y})"/>')
    return "".join(o)


def compose_html(spec: dict, palette: list[str], seed: int) -> str:
    """spec: motif, layout (top|bottom), overlay_text, cta_label."""
    rnd = random.Random(seed)
    bg, acc, light, pop = palette
    motif = spec["motif"] if spec["motif"] in MOTIFS else "orb_glow"
    top = spec.get("layout") == "top"
    panel_y = 40 if top else 660
    panel_fill = bg
    ink = spec.get("ink") or ink_for(panel_fill)
    btn_ink = ink_for(pop)
    text = html.escape(spec["overlay_text"])
    cta = html.escape(spec["cta_label"])
    art_shift = 300 if top else 0
    if spec.get("bg_image"):  # diffusion output goes under the same text panel
        art_layer = f'<image href="{spec["bg_image"]}" width="{SIZE}" height="{SIZE}" preserveAspectRatio="xMidYMid slice"/>'
    else:
        art_layer = f'<g transform="translate(0 {art_shift})">{_art(motif, palette, rnd)}</g>'
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@600;700&display=swap" rel="stylesheet">
<style>html,body{{margin:0;background:{bg}}}svg{{display:block}}
.t{{font-family:'Fredoka','DejaVu Sans',sans-serif;font-weight:700}}</style></head><body>
<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">
<defs><filter id="grain"><feTurbulence type="fractalNoise" baseFrequency=".8" numOctaves="2" seed="{seed % 97}"/><feColorMatrix values="0 0 0 0 .5  0 0 0 0 .5  0 0 0 0 .5  0 0 0 .14 0"/></filter></defs>
<rect width="{SIZE}" height="{SIZE}" fill="{bg}"/>
{art_layer}
<rect width="{SIZE}" height="{SIZE}" filter="url(#grain)"/>
<rect x="50" y="{panel_y}" width="980" height="360" rx="44" fill="{panel_fill}" opacity=".93"/>
<foreignObject x="90" y="{panel_y + 20}" width="900" height="190"><div xmlns="http://www.w3.org/1999/xhtml" class="t" style="color:{ink};font-size:{_fs(spec['overlay_text'])}px;line-height:1.08;display:flex;align-items:center;height:100%">{text}</div></foreignObject>
<g transform="translate(90 {panel_y + 225})">
<rect width="{ 70 + len(spec['cta_label'])*26 }" height="96" rx="48" fill="{pop}"/>
<text x="{(70 + len(spec['cta_label'])*26)/2}" y="64" text-anchor="middle" class="t" font-size="46" fill="{btn_ink}" style="font-family:'Fredoka','DejaVu Sans',sans-serif;font-weight:700">{cta}</text></g>
</svg></body></html>"""


def _fs(t):
    n = len(t)
    return 104 if n <= 14 else 88 if n <= 22 else 74


def chrome_png(html_path: Path, png_path: Path, size=SIZE):
    exe = shutil.which("google-chrome") or shutil.which("chromium")
    if not exe:
        raise RuntimeError("Chrome not found")
    subprocess.run([exe, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                    f"--window-size={size},{size}", "--virtual-time-budget=4000",
                    f"--screenshot={png_path}", f"file://{html_path}"],
                   check=True, capture_output=True, timeout=60)


def render_svg_ad(spec, palette, seed, out_png: Path):
    out_png.parent.mkdir(parents=True, exist_ok=True)
    h = out_png.with_suffix(".html")
    h.write_text(compose_html(spec, palette, seed))
    chrome_png(h.resolve(), out_png.resolve())
    return out_png
