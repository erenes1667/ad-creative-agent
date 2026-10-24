"""Contact-sheet HTML from a manifest."""
import html
from pathlib import Path

CSS = """:root{--bg:#fff;--fg:#1b1b24;--mut:#5b5b6b;--card:#f4f4f8;--line:#dcdce6}
@media(prefers-color-scheme:dark){:root{--bg:#14141b;--fg:#ececf3;--mut:#a3a3b5;--card:#1d1d27;--line:#33334a}}
body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:auto}h1{font-size:1.5rem}.note{color:var(--mut)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.card img{width:100%;border-radius:8px;display:block}.rk{font-weight:700}
.m{font-size:.85rem;color:var(--mut)}.bad{color:#b3261e}"""


def _card(c, rank=None, reason=None):
    e = html.escape
    img = f'<img src="{e(c["image"])}" alt="{e(c["art"]["overlay_text"])}">' if "image" in c else ""
    meta = c["copy"]["meta"]
    fails = "".join(f'<div class="bad">{e(f)}</div>' for f in c.get("gate_failures", []))
    sc = f' | score {c["score"]}' if "score" in c else ""
    return f"""<div class="card">{img}<div class="rk">{f'#{rank} ' if rank else ''}{e(c['id'])}{sc}</div>
<div><b>{e(meta['headline'])}</b></div><div>{e(meta['text'])} [{e(meta['cta'])}]</div>
<div class="m">{e(c['audience'])} | {e(c['hook_line'])}</div>{f'<p>{e(reason)}</p>' if reason else ''}{fails}</div>"""


def write_contact_sheet(m: dict, path: Path):
    by_id = {c["id"]: c for c in m["concepts"]}
    top_ids = [t["id"] for t in m["top"]]
    top = "".join(_card(by_id[t["id"]], t["rank"], t["reason"]) for t in m["top"])
    rest = "".join(_card(c) for c in m["concepts"] if c["id"] not in top_ids)
    body = f"""<h1>{html.escape(m['brief']['name'])}: contact sheet</h1>
<p class="note">Fictional product, synthetic demo. Run {html.escape(m['run_id'])}, mode {m['mode']}, image backend {html.escape(m['image_backend']['name'])}, cost USD {m['cost']['usd']}.</p>
{'<h2>Top picks</h2><div class="grid">' + top + '</div>' if top else ''}
<h2>{'Not selected' if top else 'All concepts (copy only)'}</h2><div class="grid">{rest}</div>"""
    path.write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Contact sheet</title><style>{CSS}</style></head><body><main>{body}</main></body></html>')
