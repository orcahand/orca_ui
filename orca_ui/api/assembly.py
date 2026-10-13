"""Assembly-only progress storage, independent of the connected hand.

The desktop shell uses a disposable browser profile. Keeping this one document
on the server lets the build guide resume after the shell or server restarts.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

ShortString = Annotated[str, Field(max_length=300)]


class Build(BaseModel):
    audience: Literal["internal", "external"] = "internal"
    side: Literal["left", "right"] = "right"
    motor: Literal["dynamixel", "feetech"] = "dynamixel"
    version: Literal["base", "touch", "full"] = "base"


class AssemblyProgress(BaseModel):
    current: ShortString = "p1"
    done: list[ShortString] = Field(default_factory=list, max_length=200)
    tendons: list[Annotated[int, Field(ge=0, le=31)]] = Field(default_factory=list, max_length=32)
    checks: list[ShortString] = Field(default_factory=list, max_length=200)
    views: dict[ShortString, ShortString] = Field(default_factory=dict, max_length=200)
    build: Build = Field(default_factory=Build)


def build_router(path: Path | None = None) -> APIRouter:
    path = path or Path.home() / ".orca_ui" / "assembly-progress-v2.json"
    router = APIRouter(prefix="/api/assembly", tags=["assembly"])
    lock = threading.Lock()

    @router.get("/progress")
    def read_progress():
        with lock:
            if not path.exists():
                return None
            try:
                return AssemblyProgress.model_validate_json(path.read_text())
            except (OSError, ValueError) as exc:
                raise HTTPException(503, "Assembly progress could not be read") from exc

    @router.put("/progress")
    def write_progress(progress: AssemblyProgress):
        temporary = None
        with lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
                    temporary = file.name
                    json.dump(progress.model_dump(), file)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, path)
            except OSError as exc:
                raise HTTPException(503, "Assembly progress could not be saved") from exc
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
        return {"saved": True}

    return router
