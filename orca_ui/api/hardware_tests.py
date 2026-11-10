"""REST routes of the Tests tab (``/api/hardware-tests``).

Always mounted; while the tab is not enabled ``GET /state`` answers
``enabled: false`` and every write is a 404.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from orca_ui.hardware_tests.session import HardwareTests, HardwareTestsError
from orca_ui.hardware_tests.store import display_path


class SessionRequest(BaseModel):
    plan_id: str = Field(max_length=100)
    hand_label: Optional[str] = Field(default=None, max_length=100)


class StepResultRequest(BaseModel):
    status: Literal["pass", "fail", "observed", "skipped"]
    note: str = Field(default="", max_length=5000)


class AutoRunRequest(BaseModel):
    step_ids: Optional[list[str]] = Field(default=None, max_length=200)
    force: bool = False


def build_router(tests: HardwareTests) -> APIRouter:
    router = APIRouter(prefix="/api/hardware-tests", tags=["hardware-tests"])

    def guard(fn, *args, **kwargs):
        if not tests.enabled:
            raise HTTPException(404, "the Tests tab is not enabled (start with --hardware-tests or a development orca_core)")
        try:
            return fn(*args, **kwargs)
        except HardwareTestsError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)

    def on_session(action):
        """Apply ``action`` to the open session and answer with the session."""
        def run():
            session = tests.require_session()
            action(session)
            return session.as_dict()
        return guard(run)

    @router.get("/state")
    def state():
        return tests.state()

    @router.post("/session")
    def start_session(body: SessionRequest):
        return guard(lambda: tests.start(body.plan_id, body.hand_label).as_dict())

    @router.post("/session/end")
    def end_session():
        guard(tests.end)
        return {}

    @router.post("/steps/{step_id}/open")
    def open_step(step_id: str):
        return on_session(lambda session: session.open(step_id))

    @router.post("/steps/{step_id}/close")
    def close_step(step_id: str):
        return on_session(lambda session: session.close(step_id))

    @router.post("/steps/{step_id}/result")
    def decide_step(step_id: str, body: StepResultRequest):
        return on_session(lambda session: session.decide(step_id, body.status, body.note))

    @router.post("/steps/{step_id}/screenshot")
    async def screenshot(step_id: str, request: Request):
        png = await request.body()
        path = await run_in_threadpool(guard, lambda: tests.require_session().screenshot(step_id, png))
        return {"file": display_path(path)}

    @router.post("/auto/run")
    def run_auto(body: Optional[AutoRunRequest] = None):
        body = body or AutoRunRequest()
        return on_session(lambda session: session.run_auto(body.step_ids, body.force))

    @router.post("/auto/stop")
    def stop_auto():
        return on_session(lambda session: session.stop_auto())

    return router
