"""Package the four refined assembly GLBs without changing their geometry."""
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
KEYS = [f"{version}-{side}-dynamixel" for version in ("base", "touch")
        for side in ("left", "right")]


def main():
    target = ROOT / "orca_ui" / "models" / "assembly"
    target.mkdir(parents=True, exist_ok=True)
    sources = {key: ROOT / "frontend/public/assembly/parts" / key / "assembly.glb"
               for key in KEYS}
    for source in sources.values():
        if not source.is_file():
            raise SystemExit(f"Missing model: {source}. Restore the archives before packaging.")
    for key, source in sources.items():
        with tempfile.TemporaryDirectory(dir=target) as work:
            archive = Path(work) / f"{key}.zip"
            with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as zipped:
                zipped.write(source, "assembly.glb")
            if archive.stat().st_size >= 100 * 1024 * 1024:
                raise SystemExit(f"{key}.zip exceeds 100 MiB; reduce the asset before publishing.")
            archive.replace(target / archive.name)
        print(f"{key}.zip: {(target / archive.name).stat().st_size / 1024**2:.1f} MiB")


if __name__ == "__main__":
    main()
