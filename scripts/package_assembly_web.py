"""Stage the standalone assembly guide for static hosting (assembly.orcahand.com).

    python scripts/package_assembly_web.py OUT_DIR --slug SLUG --models-base URL

Builds frontend/vite.assembly.config.ts and places the guide under OUT_DIR/SLUG/
so it is reachable only by its link; the site root serves nothing. Clips no
step references are left out, and so are the Touch assets. The assembly GLBs exceed the host's
deployment size, so they are not copied: vercel.json rewrites their paths to
MODELS_BASE/<key>/assembly.glb (upload them with --extract-models first).
The slug is the secret: pass it in, never commit it (this repo is public).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
# The public guide is Base only (the web build locks the version); Touch is
# still work in progress, so none of its models or media ship.
KEYS = [f"base-{side}-dynamixel" for side in ("left", "right")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--models-base", required=True)
    parser.add_argument("--extract-models", type=Path,
                        help="also unzip the GLBs into this directory for upload")
    args = parser.parse_args()

    subprocess.run(["npx", "vite", "build", "-c", "vite.assembly.config.ts"],
                   cwd=FRONTEND, check=True)
    dist = FRONTEND / "dist-assembly"
    if args.out.exists():
        shutil.rmtree(args.out)
    site = args.out / args.slug
    shutil.copytree(dist, site)
    (site / "assembly.html").rename(site / "index.html")

    sources = "".join(p.read_text(errors="ignore")
                      for p in (FRONTEND / "src").rglob("*") if p.is_file())
    dropped = 0
    for clip in (site / "assembly" / "clips").iterdir():
        if clip.name not in sources:
            dropped += clip.stat().st_size
            clip.unlink()
    for key in KEYS:
        (site / "assembly" / "parts" / key / "assembly.glb").unlink(missing_ok=True)
    for touch in [*(site / "assembly" / "parts").glob("touch-*"),
                  site / "assembly" / "touch"]:
        if touch.is_dir():
            dropped += sum(p.stat().st_size for p in touch.rglob("*") if p.is_file())
            shutil.rmtree(touch)

    base = args.models_base.rstrip("/")
    (args.out / "vercel.json").write_text(json.dumps({
        "cleanUrls": False,
        "trailingSlash": True,
        "headers": [{"source": "/(.*)", "headers": [
            {"key": "X-Robots-Tag", "value": "noindex, nofollow"},
            {"key": "Referrer-Policy", "value": "no-referrer"}]}],
        "rewrites": [{"source": f"/{args.slug}/assembly/parts/{key}/assembly.glb",
                      "destination": f"{base}/{key}/assembly.glb"} for key in KEYS],
    }, indent=2) + "\n")
    (args.out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (args.out / "index.html").write_text("<!doctype html><title>ORCA</title>"
                                        "<meta name=robots content=noindex>\n")

    if args.extract_models:
        for key in KEYS:
            target = args.extract_models / key
            target.mkdir(parents=True, exist_ok=True)
            with ZipFile(ROOT / "orca_ui/models/assembly" / f"{key}.zip") as zipped:
                if zipped.namelist() != ["assembly.glb"]:
                    raise SystemExit(f"Unexpected contents in {key}.zip")
                zipped.extract("assembly.glb", target)

    size = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    print(f"Staged {size / 1e6:.0f} MB at {args.out} "
          f"(dropped {dropped / 1e6:.0f} MB of unreferenced clips and Touch assets)")


if __name__ == "__main__":
    main()
