"""Motion step: a 6.5 s square clip from the top ranked images. Slow zoom plus crossfade, ffmpeg only, no video model."""
import subprocess
from pathlib import Path

SEC, FADE, FPS = 2.5, 0.5, 25  # 3 images x 2.5 s, 0.5 s crossfades = 6.5 s


def ffmpeg_cmd(images, out):
    n = len(images)
    ins = [x for p in images for x in ("-i", str(p))]
    parts = [f"[{i}:v]scale=1080:1080,zoompan=z='min(zoom+0.0008,1.12)':d={int(SEC*FPS)}:s=1080x1080:fps={FPS},format=yuv420p[v{i}]" for i in range(n)]
    last = "v0"
    for i in range(1, n):
        parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={FADE}:offset={i*(SEC-FADE)}[x{i}]")
        last = f"x{i}"
    return ["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", ";".join(parts), "-map", f"[{last}]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]


def make_clip(run_dir: Path, out: Path, top_n=3) -> Path:
    import json
    man = json.loads((Path(run_dir) / "manifest.json").read_text())
    by_id = {c["id"]: c for c in man["concepts"]}
    imgs = [Path(run_dir) / by_id[t["id"]]["image"] for t in man["top"][:top_n]]
    subprocess.run(ffmpeg_cmd(imgs, out), check=True)
    return out
