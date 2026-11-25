"""The visual-calibration page's one-time "0 · Setup" step: everything a newly built rig needs
before step 1, in order (docs/rig-setup.md). The logic is the experiment's
``visual_calibration.setup`` (the same functions its CLI runs); this module serves it:

    usb        GET (cached, opens nothing: the page's USB 2 banner polls it) / POST (fresh)
    turntable  the rig's board and motor, and whether turntable_calibration.yaml is theirs
    identify   a still of every camera by serial, its pose from the tower, the A/B assignment
    align      per camera: what to move against its mount, then lock and check again
    exposure, focus, tour   background jobs with progress (GET /setup/jobs/<id>)

Every finding goes to the rig's local.yaml (RigConfig.save_local), never config.yaml: the
serials, exposure and focus, a kept mount hole, and the results under ``setup:``. Re-running
an item is safe: it measures again and overwrites its own entries.
"""
from __future__ import annotations

import base64
import os
import threading
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

SETTLE_S = {"exposure": 0.8, "focus": 1.0, "tour": 1.0}    # after a control change / a move, before a frame
TOUR_STOPS = tuple(range(0, 316, 45))                       # 8 stops, 45° apart
AV_TTL_S = 30.0                                             # system_profiler's camera list is reused this long
THUMB_PX = 360
LIGHT_MAX_S = 30.0
RANK = {"error": 0, "not run": 1, "warn": 2, "ok": 3}

_av: dict = {}


def _av_ids(fresh: bool = False) -> list[str]:
    """AVFoundation's camera ids (system_profiler, opens nothing), reused for AV_TTL_S."""
    if fresh or time.monotonic() - _av.get("t", -1e9) > AV_TTL_S:
        from visual_calibration.uvc import avfoundation_ids
        _av.update(ids=avfoundation_ids(), t=time.monotonic())
    return _av["ids"]


def _uvcc(uvc: dict):
    """The camera's UVC controls (uvcc, its bus filter included: Uvcc.from_config)."""
    from visual_calibration.uvc import Uvcc
    return Uvcc.from_config(uvc)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _worst(statuses) -> str:
    statuses = list(statuses)
    return min(statuses, key=lambda s: RANK.get(s, 1)) if statuses else "not run"


def _status(warnings: list[dict]) -> str:
    sev = {w["severity"] for w in warnings}
    return "error" if "error" in sev else "warn" if sev else "ok"


def _thumb(img) -> str:
    import cv2
    k = min(1.0, THUMB_PX / max(img.shape[:2]))
    small = cv2.resize(img, (round(img.shape[1] * k), round(img.shape[0] * k)), interpolation=cv2.INTER_AREA)
    return base64.b64encode(cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()).decode()


class Cancelled(Exception):
    pass


class Job:
    """A long setup run (exposure, focus, tour) on its own thread: progress, a note, the result."""

    def __init__(self, kind: str, cam: str | None, total: int):
        self.id, self.kind, self.cam, self.total = uuid.uuid4().hex[:12], kind, cam, max(1, total)
        self.state, self.done, self.note = "running", 0, "starting…"
        self.result, self.error = None, None
        self.started, self.ended = time.time(), None
        self.cancel = threading.Event()

    def step(self, note: str | None = None) -> None:
        if self.cancel.is_set():
            raise Cancelled("stopped")
        self.done += 1
        if note:
            self.note = note

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "camera": self.cam, "state": self.state,
                "progress": round(min(1.0, self.done / self.total), 3), "note": self.note,
                "result": self.result, "error": self.error, "started": self.started, "ended": self.ended}


class Assignment(BaseModel):
    assignment: dict[str, str]                     # camera -> USB serial


class MountHole(BaseModel):
    cam: str
    key: str                                       # distance | height
    value: float


def add_setup_routes(router: APIRouter, ctx) -> None:
    """ctx: the visual-calibration router's rig_config, camera_cfg, table, hand, mock, vc,
    detector, motor, find_rig, connect_rig, presence."""
    from orca_ui.api import visual_calibration as vcm

    jobs: dict[str, Job] = {}
    jobs_lock = threading.Lock()
    proposal: dict = {}                            # the last identify: serials seen, for /identify/save

    def cancel_all() -> None:
        for j in list(jobs.values()):
            j.cancel.set()

    ctx.table.setdefault("on_release", []).append(cancel_all)   # E-STOP stops the jobs before the torque goes off

    def S():
        ctx.vc()
        from visual_calibration import setup
        return setup

    def record(rig, item: str, payload: dict) -> None:
        rig.save_local({"setup": {item: {**payload, "at": _now()}}})

    def still(rig, cam: str) -> tuple:
        """Camera `cam`'s frame by its serial (409 when it has none yet, or cannot be read)."""
        cfg = ctx.camera_cfg(rig, cam, enabled=True)
        if not ((cfg.get("uvc") or {}).get("device") or {}).get("serial"):
            raise HTTPException(409, f"camera {cam} has no serial yet: run Identify cameras")
        try:
            return vcm.serial_still(cam, cfg), cfg
        except HTTPException:
            raise
        except Exception as e:                     # noqa: BLE001 - a camera that cannot be read is a finding
            raise HTTPException(409, f"camera {cam}: {e}") from e

    # 1. USB -----------------------------------------------------------------------------------

    def usb_state(fresh: bool) -> dict:
        setup = S()
        rig = ctx.rig_config()
        found = setup.cameras_on_usb(rig, vcm.usb_devices(fresh), _av_ids(fresh))
        warns = setup.usb_warnings(rig, found)
        res = {c: tuple(cfg.get("resolution") or (3840, 2160)) for c, cfg in rig.cameras.items()}
        slow = [c for c in found if c["usb3"] is False and (c["camera"] is None or c["camera"] in rig.active_cameras)]
        banner = [{**w, "values": {**w["values"], "resolution": list(res.get(c["camera"] or "a", (3840, 2160)))}}
                  for w in warns if w["code"] == "usb2_link" for c in slow if c["serial"] == w["values"].get("serial")]
        return {"status": _status(warns), "cameras": found, "warnings": warns, "banner": banner,
                "active_cameras": rig.active_cameras}

    @router.get("/setup/usb")
    def setup_usb() -> dict:
        """The cameras on USB (cached listings: this opens nothing, the page polls it)."""
        return usb_state(False)

    @router.post("/setup/usb")
    def setup_usb_run() -> dict:
        out = usb_state(True)
        record(ctx.rig_config(), "usb", {"status": out["status"],
                                         "cameras": [{k: c[k] for k in ("serial", "camera", "link_mbps", "opencv_index")}
                                                     for c in out["cameras"]]})
        return out

    @router.post("/setup/light")
    def setup_light(cam: str | None = Query(None, pattern=r"^[a-z]$"), serial: str | None = Query(None, max_length=64),
                    seconds: float = Query(10.0, gt=0)) -> dict:
        """Which BRIO is which by eye: stream camera `cam` (or the one with USB `serial`, before
        serials are saved) for `seconds` (at most LIGHT_MAX_S) so its white LED lights. Returns at once."""
        rig = ctx.rig_config()
        seconds = min(float(seconds), LIGHT_MAX_S)
        if (cam is None) == (serial is None):
            raise HTTPException(400, "give cam or serial")
        if cam is not None:
            cfg = ctx.camera_cfg(rig, cam, enabled=True)
            serial = ((cfg.get("uvc") or {}).get("device") or {}).get("serial")
            if not serial:
                raise HTTPException(409, f"camera {cam} has no serial yet: light it by serial (USB card)")
        else:
            on_usb = {str(d.get("serial")) for d in vcm.usb_devices(True)}
            if serial not in on_usb:
                raise HTTPException(404, f"no camera with serial {serial} on USB")
            dev = next(iter(rig.cameras.values()))["uvc"]["device"]
            cfg = {"uvc": {"device": {"vendor": dev["vendor"], "product": dev["product"], "serial": serial}},
                   "resolution": next(iter(rig.cameras.values())).get("resolution")}
            cam = next((c for c, k in rig.cameras.items() if str(k["uvc"]["device"].get("serial")) == serial), None)
        try:
            until = vcm.light_up(serial, cfg, seconds)
        except Exception as e:                     # noqa: BLE001 - a camera that cannot be opened is a finding
            raise HTTPException(409, f"camera {cam or serial}: {e}") from e
        return {"camera": cam, "serial": serial, "seconds": round(seconds, 1),
                "remaining_s": round(max(0.0, until - time.monotonic()), 1)}

    # 2. turntable -----------------------------------------------------------------------------

    @router.post("/setup/turntable")
    def setup_turntable() -> dict:
        """The rig's board and motor (connected read-only, torque off, never the hand's board) and
        whether the motor calibration is theirs."""
        setup = S()
        if "t" not in ctx.table:
            found = None if ctx.mock else ctx.find_rig(True)       # never the hand's ports
            if ctx.mock or found is not None:
                ctx.connect_rig(found)
        t = ctx.table.get("t")
        rig = ctx.rig_config()
        if t is None:
            out = {"calibrated": False, "board": None, "warnings": [
                {"code": "rig_board_missing", "severity": "error", "message": "The turntable's board is not on USB.",
                 "fix": "Plug in the rig board (not the hand's) and power the motor; then run this again.",
                 "values": {"presence": ctx.presence.get("warnings", [])}}]}
        else:
            out = setup.turntable_status(rig, t.bus)
            out["mock"] = bool(t.mock)
            if t.bus is None and not out["calibrated"]:
                out["warnings"].append({"code": "turntable_uncalibrated", "severity": "error",
                                        "message": "The turntable motor is not calibrated.",
                                        "fix": "Run the motor calibration (homes into the stop 3x, runs the travel).",
                                        "values": {}})
            out["state"] = t.state().as_dict()
        status = _status(out["warnings"])
        record(rig, "turntable", {"status": status, "calibrated": out["calibrated"],
                                  "board": out.get("board"), "codes": [w["code"] for w in out["warnings"]]})
        return {"status": status, **out}

    # 3. identify ------------------------------------------------------------------------------

    @router.post("/setup/identify")
    def setup_identify() -> dict:
        """With the tower on the plate (parked at sweep.REFERENCE_STOP when the motor is calibrated):
        a still of every camera on USB by serial, its pose from the tower, the A/B assignment.
        Saved at once only when sure and no serial was set before; else /setup/identify/save."""
        setup = S()
        from visual_calibration.sweep import REFERENCE_STOP
        rig = ctx.rig_config()
        t = ctx.table.get("t")
        parked = None
        if t is not None and t.zero is not None and t.state().calibrated:
            settle = rig.stops.settle_s
            ctx.motor(lambda tt: tt.move(REFERENCE_STOP, settle, hold=False))
            parked = REFERENCE_STOP
        found = setup.cameras_on_usb(rig, vcm.usb_devices(True), _av_ids(True))
        first = next(iter(rig.cameras.values()))
        dev = first["uvc"]["device"]
        det = ctx.detector()
        cams, poses = [], {}
        for c in found:
            if not c["serial"]:
                continue
            cfg = {"uvc": {"device": {"vendor": dev["vendor"], "product": dev["product"], "serial": c["serial"]}},
                   "resolution": first.get("resolution")}
            entry = {"serial": c["serial"], "configured_as": c["camera"], "usb3": c["usb3"]}
            try:
                img = vcm.serial_still(c["serial"], cfg)
            except Exception as e:                 # noqa: BLE001 - shown on its card
                entry["error"] = str(e)
                poses[c["serial"]] = None
                cams.append(entry)
                continue
            dets = det.detect(img)
            pose = setup.single_view_pose(det.obj, dets, (img.shape[1], img.shape[0]),
                                          float(first.get("diagonal_fov_deg", 90.0)))
            poses[c["serial"]] = pose
            cams.append({**entry, "pose": pose, "tiles": len(dets), "image": _thumb(img),
                         "size": [int(img.shape[1]), int(img.shape[0])]})
        ident = setup.identify(rig, poses)
        before = {c: rig.cameras[c]["uvc"]["device"].get("serial") for c in rig.active_cameras}
        had = {c: s for c, s in before.items() if s}
        disagree = bool(had) and any(had.get(c) not in (None, s) for c, s in ident["assignment"].items())
        saved = False
        if ident["confident"] and not had and ident["assignment"]:
            save_serials(ident["assignment"])
            saved = True
        proposal.clear()
        proposal.update(serials={c["serial"] for c in cams})
        agrees = all(had.get(c) == s for c, s in ident["assignment"].items())
        status = "error" if not ident["assignment"] else "ok" if saved or agrees else "warn"   # warn: confirm it
        out = {"status": status, "cameras": cams, "identify": ident, "before": before, "disagree": disagree,
               "saved": saved, "parked_at": parked,
               "nominal": {c: setup.nominal_view(rig, c) for c in rig.active_cameras}}
        record(ctx.rig_config(), "identify", {"status": status, "assignment": ident["assignment"],
                                              "confident": ident["confident"], "saved": saved})
        return out

    def save_serials(assignment: dict[str, str]) -> None:
        rig = ctx.rig_config()
        rig.save_local({"cameras": {c: {"uvc": {"device": {"serial": str(s)}}} for c, s in assignment.items()}})

    @router.post("/setup/identify/save")
    def setup_identify_save(body: Assignment) -> dict:
        """The confirmed assignment: each camera's serial into local.yaml."""
        rig = ctx.rig_config()
        a = body.assignment
        if not a or set(a) - set(rig.active_cameras):
            raise HTTPException(400, f"cameras must be among {rig.active_cameras}")
        if len(set(a.values())) != len(a):
            raise HTTPException(400, "one serial per camera")
        if proposal.get("serials") is not None and set(a.values()) - proposal["serials"]:
            raise HTTPException(400, "a serial that the last identify did not see")
        save_serials(a)
        record(ctx.rig_config(), "identify", {"status": "ok", "assignment": a, "confirmed": True})
        return {"status": "ok", "assignment": a}

    # 4. align ---------------------------------------------------------------------------------

    def measure(cam: str) -> dict:
        setup = S()
        rig = ctx.rig_config()
        img, cfg = still(rig, cam)
        det = ctx.detector()
        dets = det.detect(img)
        pose = setup.single_view_pose(det.obj, dets, (img.shape[1], img.shape[0]),
                                      float(cfg.get("diagonal_fov_deg", 90.0)))
        letters = rig.raw["calibration_object"].get("letters") or {}
        base = {"camera": cam, "size": [int(img.shape[1]), int(img.shape[0])],
                "tiles": sorted(letters.get(d.tile, d.tile) for d in dets), "pose": pose}
        if pose is None:
            return {**base, "ok": False, "placement": None,
                    "advice": ["fewer than 12 tower corners seen: is the tower on the plate, in view and lit?"]}
        place = setup.placement(rig, cam, pose)
        return {**base, "ok": place["ok"], "placement": place, "advice": place["advice"]}

    @router.get("/setup/align")
    def setup_align(cam: str = vcm.CAMERA) -> dict:
        """Where camera `cam` sits against its mount, from a still by serial (the page asks ~2 s)."""
        return measure(cam)

    @router.post("/setup/align/check")
    def setup_align_check(cam: str = vcm.CAMERA, locked: bool = Query(False)) -> dict:
        """Measure again; with locked=true (the screws tightened) a pass is the item's green."""
        out = measure(cam)
        status = "ok" if out["ok"] and locked else "warn" if out["ok"] else "error"
        record(ctx.rig_config(), "align", {cam: {"status": status, "locked": locked and out["ok"],
                                                 "found": (out["placement"] or {}).get("found")}})
        return {**out, "status": status, "locked": locked}

    @router.post("/setup/mount")
    def setup_mount(body: MountHole) -> dict:
        """Keep the camera where it is: its mount hole into local.yaml (it must be a hole)."""
        from visual_calibration.rig_config import RigConfigError
        rig = ctx.rig_config()
        opts = ((ctx.camera_cfg(rig, body.cam).get("mount") or {}).get("options") or {})
        if body.key not in opts:
            raise HTTPException(400, f"mount.{body.key} has no holes to choose (options: {sorted(opts)})")
        path = rig.local_path
        old = open(path).read() if os.path.exists(path) else None
        rig.save_local({"cameras": {body.cam: {"mount": {body.key: float(body.value)}}}})
        try:
            ctx.rig_config()
        except RigConfigError as e:
            if old is None:
                os.remove(path)
            else:
                open(path, "w").write(old)
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "camera": body.cam, body.key: float(body.value)}

    # 5./6./7. jobs ----------------------------------------------------------------------------

    def start(kind: str, cam: str | None, total: int, work) -> dict:
        """One setup job at a time (they share the cameras and the plate)."""
        job = Job(kind, cam, total)
        with jobs_lock:
            busy = next((j for j in jobs.values() if j.state == "running"), None)
            if busy is not None:
                raise HTTPException(409, f"{busy.kind}{f' ({busy.cam})' if busy.cam else ''} is still running")
            jobs[job.id] = job

        def run():
            try:
                job.result = work(job)
                job.state, job.note = "done", "done"
            except Cancelled:
                job.state, job.note = "cancelled", "stopped"
            except HTTPException as e:
                job.state, job.error = "failed", str(e.detail)
            except Exception as e:                 # noqa: BLE001 - a job reports, never kills the server
                job.state, job.error = "failed", f"{type(e).__name__}: {e}"
            finally:
                job.ended = time.time()
        threading.Thread(target=run, daemon=True, name=f"setup-{kind}").start()
        return job.as_dict()

    def counting(grab, job: Job, what: str):
        def g():
            job.step(what)
            return grab()
        return g

    def tuned(kind: str, cam: str) -> dict:
        rig = ctx.rig_config()
        cfg = ctx.camera_cfg(rig, cam, enabled=True)
        if not ((cfg.get("uvc") or {}).get("device") or {}).get("serial"):
            raise HTTPException(409, f"camera {cam} has no serial yet: run Identify cameras")
        if not cfg.get("uvc"):
            raise HTTPException(409, f"camera {cam} has no uvc block in the rig config")
        total = 6 if kind == "exposure" else len(range(0, 121, 8)) + 9

        def work(job: Job) -> dict:
            from visual_calibration.uvc import ensure
            setup = S()
            uvc = cfg["uvc"]
            u = _uvcc(uvc)
            job.note = "locking the camera's controls"
            ensure(u, uvc, write=True)
            grab = counting(lambda: vcm.serial_still(cam, cfg), job, f"{kind}: frame")
            det = ctx.detector()
            try:
                if kind == "exposure":
                    res = setup.tune_exposure(u, grab, det, int(uvc.get("power_line_frequency", 1)),
                                              settle_s=SETTLE_S["exposure"])
                    value = {"absolute_exposure_time": res["exposure"]}
                    summary = {"status": "warn" if res["dim"] else "ok", "exposure": res["exposure"],
                               "brightness": res["brightness"], "dim": res["dim"], "sweep": res["sweep"]}
                else:
                    letters = rig.raw["calibration_object"].get("letters") or {}
                    res = setup.focus_coarse_fine(u, grab, det, letters, settle_s=SETTLE_S["focus"])
                    value = {"absolute_focus": res["focus"]}
                    curve = [[r["focus"], r["worst"], r["mean"]] for r in res["sweep"]]
                    coarse = [[r["focus"], r.get("worst"), r.get("mean")] for r in res.get("coarse", [])]
                    summary = {"status": "ok" if res["worst"] >= 0.8 else "warn", "focus": res["focus"],
                               "worst": res["worst"], "mean": res["mean"], "curve": curve, "coarse": coarse}
            except BaseException:
                try:
                    ensure(u, uvc, write=True)     # back to the configured values
                except Exception:                  # noqa: BLE001 - the job's own error is the one to show
                    pass
                raise
            rig.save_local({"cameras": {cam: {"uvc": value}}})
            fresh = ctx.rig_config()
            uvc2 = fresh.cameras[cam]["uvc"]
            job.note = "locking the new value"
            ensure(_uvcc(uvc2), uvc2, write=True)
            record(fresh, kind, {cam: summary})
            return summary
        return start(kind, cam, total, work)

    @router.post("/setup/exposure")
    def setup_exposure(cam: str = vcm.CAMERA) -> dict:
        """Background job: lock the controls, then the shortest flicker-safe exposure that lights
        the tiles; saved to local.yaml and locked."""
        return tuned("exposure", cam)

    @router.post("/setup/focus")
    def setup_focus(cam: str = vcm.CAMERA) -> dict:
        """Background job: the focus where every visible tile is sharp together (coarse, then fine)."""
        return tuned("focus", cam)

    @router.post("/setup/tour")
    def setup_tour() -> dict:
        """Background job: the plate through 8 stops, a frame per camera: every tile seen by some camera.
        Torque off after each move; the plate waits for the hand; E-STOP stops it."""
        t = ctx.table.get("t")
        if t is None or t.zero is None:
            raise HTTPException(409, "connect and home (or calibrate) the turntable first")
        if (reason := ctx.hand["blocker"]()):
            raise HTTPException(409, reason)
        rig = ctx.rig_config()
        cams = [c for c in rig.active_cameras if rig.cameras[c]["uvc"]["device"].get("serial")]
        if not cams:
            raise HTTPException(409, "no camera has a serial yet: run Identify cameras")

        def work(job: Job) -> dict:
            setup = S()
            det = ctx.detector()
            letters = rig.raw["calibration_object"].get("letters") or {}
            grabs = {c: counting(lambda c=c: vcm.serial_still(c, rig.cameras[c]), job, f"camera {c}") for c in cams}

            class Guarded:
                def move(self, angle: float, settle_s: float = 0.0):
                    if job.cancel.is_set():
                        raise Cancelled("stopped")
                    if (reason := ctx.hand["blocker"]()):
                        raise HTTPException(409, reason)
                    job.note = f"turning to {angle:g}°"
                    ctx.table["moving"] = True
                    try:
                        return t.move(angle, settle_s, hold=False)
                    finally:
                        ctx.table["moving"] = False
            try:
                res = setup.tour(Guarded(), grabs, det, letters, stops=TOUR_STOPS, settle_s=SETTLE_S["tour"])
            finally:
                t.release()
            summary = {"status": _status(res["warnings"]), "seen": res["seen"], "missing": res["missing"],
                       "stops": res["stops"], "warnings": res["warnings"]}
            record(ctx.rig_config(), "tour", summary)
            return summary
        return start("tour", None, len(TOUR_STOPS) * len(cams), work)

    @router.get("/setup/jobs/{job_id}")
    def setup_job(job_id: str) -> dict:
        j = jobs.get(job_id)
        if j is None:
            raise HTTPException(404, f"no setup job {job_id}")
        return j.as_dict()

    @router.post("/setup/jobs/{job_id}/cancel")
    def setup_job_cancel(job_id: str) -> dict:
        j = jobs.get(job_id)
        if j is None:
            raise HTTPException(404, f"no setup job {job_id}")
        j.cancel.set()
        return j.as_dict()

    # summary ----------------------------------------------------------------------------------

    @router.get("/setup")
    def setup_summary() -> dict:
        """Every item's last result (local.yaml setup:, so it survives a reload), the live USB
        check, the running jobs, and what blocks 1 · Rig."""
        rig = ctx.rig_config()
        local = rig.load_local()
        done = local.get("setup") or {}
        cams = rig.active_cameras
        local_uvc = {c: ((local.get("cameras") or {}).get(c) or {}).get("uvc") or {} for c in cams}
        try:
            usb = usb_state(False)
        except Exception as e:                     # noqa: BLE001 - the listing failed: say so on the card
            usb = {"status": "error", "warnings": [{"code": "usb_listing", "severity": "error", "message": str(e),
                                                    "fix": "", "values": {}}], "banner": [], "cameras": []}

        def item(key: str) -> dict:
            return dict(done.get(key) or {"status": "not run"})

        def per_cam(key: str, value_key: str | None = None, value: str | None = None) -> dict:
            out = {}
            for c in cams:
                got = (done.get(key) or {}).get(c)
                if got is None and value_key and local_uvc[c].get(value_key) is not None:
                    got = {"status": "ok", value: local_uvc[c][value_key], "from": "local.yaml"}
                out[c] = got or {"status": "not run"}
            return {"status": _worst(v["status"] for v in out.values()), "cameras": out}

        identify = item("identify")
        serials = {c: rig.cameras[c]["uvc"]["device"].get("serial") for c in cams}
        if all(serials.values()) and identify["status"] == "not run":
            identify = {**identify, "status": "ok", "serials": serials, "from": "local.yaml"}
        if not all(serials.values()):
            identify = {**identify, "status": "error" if identify["status"] == "ok" else identify["status"],
                        "missing": [c for c, s in serials.items() if not s]}
        items = {"usb": {**item("usb"), "status": usb["status"], "live": usb},
                 "turntable": item("turntable"), "identify": identify,
                 "align": per_cam("align"), "exposure": per_cam("exposure", "absolute_exposure_time", "exposure"),
                 "focus": per_cam("focus", "absolute_focus", "focus"), "tour": item("tour")}
        titles = {"usb": "USB", "turntable": "Turntable", "identify": "Identify cameras", "align": "Align cameras",
                  "exposure": "Exposure", "focus": "Focus", "tour": "Tile tour"}
        blockers = [f"{titles[k]}: {v['status']}" for k, v in items.items() if v["status"] in ("error", "not run")]
        return {"items": items, "ready": not blockers, "blockers": blockers, "cameras": cams,
                "jobs": [j.as_dict() for j in sorted(jobs.values(), key=lambda j: j.started)][-10:]}
