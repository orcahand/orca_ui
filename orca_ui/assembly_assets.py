"""Restore the assembly guide's local models from its bundled ZIP archives."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile
import zlib

PACKAGE_DIR = Path(__file__).resolve().parent
MODEL_KEYS = tuple(f"{version}-{side}-dynamixel" for version in ("base", "touch")
                   for side in ("left", "right"))
logger = logging.getLogger(__name__)


def _signature(path: Path, crc: int, size: int) -> dict:
    stat = path.stat()
    return {"crc": crc, "size": size, "mtime_ns": stat.st_mtime_ns}


def _restore(archive: Path, directory: Path) -> bool:
    """Validate existing output or atomically replace it. Never extract ZIP paths."""
    output = directory / "assembly.glb"
    marker = directory / ".assembly-model.json"
    directory.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive) as zipped:
        if zipped.namelist() != ["assembly.glb"]:
            raise ValueError(f"Unexpected contents in {archive.name}")
        member = zipped.getinfo("assembly.glb")
        if output.is_file() and output.stat().st_size == member.file_size:
            signature = _signature(output, member.CRC, member.file_size)
            try:
                if json.loads(marker.read_text()) == signature:
                    return False
            except (OSError, ValueError):
                pass
            crc = 0
            with output.open("rb") as existing:
                for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                    crc = zlib.crc32(chunk, crc)
            if crc == member.CRC:
                marker.write_text(json.dumps(signature))
                return False

        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as dest:
                temporary = Path(dest.name)
                with zipped.open(member) as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        dest.write(chunk)
                dest.flush()
                os.fsync(dest.fileno())
            with temporary.open("rb") as extracted:
                if extracted.read(4) != b"glTF":
                    raise ValueError(f"Invalid GLB in {archive.name}")
            os.replace(temporary, output)
            marker.write_text(json.dumps(_signature(output, member.CRC, member.file_size)))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return True


def prepare_assembly_models(package_dir: Path = PACKAGE_DIR) -> list[str]:
    """Restore packaged assets and, in a checkout, Vite's source assets.

    Failures remain local to the guide and never prevent the console starting.
    All locations are resolved relative to this package, not the shell's cwd.
    """
    archives = package_dir / "models" / "assembly"
    targets = [package_dir / "webui" / "assembly" / "parts"]
    source = package_dir.parent / "frontend" / "public" / "assembly" / "parts"
    if source.is_dir() and (package_dir.parent / "frontend" / "package.json").is_file():
        targets.append(source)
    errors = []
    for key in MODEL_KEYS:
        for target in targets:
            try:
                if _restore(archives / f"{key}.zip", target / key):
                    logger.info("Extracted assembly model %s to %s", key, target)
            except Exception as exc:
                message = f"Assembly model {key}: {exc}"
                errors.append(message)
                logger.warning("%s. Retry with python -m orca_ui.assembly_assets", message)
    return errors


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    failures = prepare_assembly_models()
    if failures:
        raise SystemExit(1)
    print("Assembly models are ready. Reload the guide to view them.")
