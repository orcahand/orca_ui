// Visual calibration (orca_core VISUAL_CALIBRATION.md): one fixed camera, the
// plate turning in front of it on the rig's motor. A subroutine of seven steps
// in two phases, freely switchable: rig (the calibration object instead of the
// hand: set up, then 1a the camera and 1b the rotation, each a motor sweep
// through every stop and a solve) and hand (the hand on the same connector, a
// sweep with no solve yet). Each step shows what to do as a line drawing of the
// rig, the plate's stops from above, and the live camera with the tiles it
// finds, where those matter. A step's state comes from its session where the
// session can tell (photos, solve), else from the operator having moved past it.
// Without a motor, the plate can still be turned by hand to each stop. Over the
// video, the model as the camera should see it (tiles on the rig steps, the
// hand URDF on the hand steps): the rigid parts line up when the rig is right.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { SetupTabs } from "../setup/SetupTabs";
import { api } from "../../api/rest";
import { useAppStore } from "../../state/appStore";
import {
  grabFrame,
  visualApi,
  type Detected,
  type LiveFit,
  type ModelOverlay,
  type RigInfo,
  type Session,
  type SessionKind,
  type SessionListItem,
  type Turntable,
} from "./api";
import { usePageVisible } from "../common/usePageVisible";
import { drawTiles } from "./drawTiles";
import { STEPS, type StepDef, type StepId } from "./instructions";
import { HandBoard } from "./HandBoard";
import { Results } from "./Results";
import { fitOf, solvedWell } from "./solve";
import type { HandOverlay } from "./handOverlay";
import { StepArt } from "./StepArt";
import { StopDial } from "./StopDial";
import { ControlSandbox } from "./ControlSandbox";
import { latest } from "../../state/streamStore";

const CAMERA_KEY = "orca-ui.visual-calibration.camera";
const ROTATION_KEY = "orca-ui.visual-calibration.rotation";
const ROTATION_MANUAL_KEY = "orca-ui.visual-calibration.rotation-manual";
const STEP_KEY = "orca-ui.visual-calibration.wizard-step";
const CONFIRMED_KEY = "orca-ui.visual-calibration.confirmed";
const SAVED_KEY = "orca-ui.visual-calibration.saved-sessions";
const BY_HAND_KEY = "orca-ui.visual-calibration.by-hand";
const OVERLAY_KEY = "orca-ui.visual-calibration.overlay";
const MOUNT_HAND_KEY = "orca-ui.visual-calibration.overlay-hand";
const VIEW_KEY = "orca-ui.visual-calibration.view";
const SOLVE_JOINTS_KEY = "orca-ui.visual-calibration.solve-joints";
const SEARCH_EVERY = 5; // solves between the per-finger grid searches
const ROTATIONS = [0, 90, 180, 270] as const;
type Rotation = (typeof ROTATIONS)[number];
const PREFERRED = /brio/i;
const LIVE_MS = 700;
const WEAK = 32;
const KINDS: SessionKind[] = ["camera", "rotation", "hand"];

type StepState = "done" | "warn" | "todo";
type Issue = { text: string; fix: "camera-step" | "mount" | null };
type Action = {
  label: string;
  title: string;
  onClick: () => void;
  primary: boolean;
  disabled?: boolean;
  key?: string;
};

function stored<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}

function store(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* private mode */
  }
}

// A solve that refuses: the rotation needs a solved camera step first; a camera
// far from the configured mount means the mount setting is wrong.
function issueOf(message: string): Issue {
  if (/solve the camera step first/i.test(message))
    return { text: message, fix: "camera-step" };
  if (/from where the rig config puts it/i.test(message))
    return { text: message, fix: "mount" };
  return { text: message, fix: null };
}

type Layers = {
  model: ModelOverlay | null;
  tiles: boolean;
  hand: HandOverlay | null;
  letters: Record<string, string>;
  fit?: LiveFit | null; // the camera-only pose estimate
  estimate?: HandOverlay | null; // the URDF at the estimate (pose + mount)
  zero?: HandOverlay | null; // the URDF at zero on the CAD mount, for comparison
  target?: { pose: Record<string, number>; mount: number[][] | null } | null; // the sandbox's wanted pose
};

type LayerKey =
  | "tiles"
  | "detected"
  | "hand"
  | "cad"
  | "fit"
  | "seg"
  | "edges"
  | "estimate"
  | "zero";
type ViewMode = "camera" | "overlay" | "seg" | "seg-model";
const MODES: [ViewMode, string][] = [
  ["camera", "camera"],
  ["overlay", "camera + overlay"],
  ["seg", "segmentation only"],
  ["seg-model", "segmentation + model"],
];
type LayerStyle = { color: string; opacity: number };
type ViewSettings = {
  open: boolean;
  mode: ViewMode;
  fade: number; // 0..0.8: the camera image dimmed and desaturated
  layers: Record<LayerKey, LayerStyle>;
};
const LAYER_NAMES: Record<LayerKey, string> = {
  tiles: "tiles",
  detected: "detected",
  hand: "hand",
  cad: "CAD",
  fit: "fit",
  seg: "hand mask",
  edges: "edges",
  estimate: "estimate",
  zero: "CAD at 0",
};
const DEFAULT_VIEW: ViewSettings = {
  open: false,
  mode: "overlay",
  fade: 0,
  layers: {
    tiles: { color: "#22d3ee", opacity: 1 },
    detected: { color: "#34d399", opacity: 1 },
    hand: { color: "#22d3ee", opacity: 1 },
    cad: { color: "#f59e0b", opacity: 0.95 },
    fit: { color: "#22c55e", opacity: 0.95 },
    seg: { color: "#3b82f6", opacity: 0.6 },
    edges: { color: "#f8fafc", opacity: 1 },
    estimate: { color: "#22c55e", opacity: 1 },
    zero: { color: "#f59e0b", opacity: 0 },
  },
};

function loadView(): ViewSettings {
  const v = stored<Partial<ViewSettings>>(VIEW_KEY, {});
  return {
    open: !!v.open,
    mode: MODES.some(([m]) => m === v.mode) ? (v.mode as ViewMode) : "overlay",
    fade: typeof v.fade === "number" ? v.fade : 0,
    layers: { ...DEFAULT_VIEW.layers, ...(v.layers ?? {}) },
  };
}

// The camera-only joint estimate: degrees in the URDF's convention, 1-sigma, and how
// sure the view is (poor: it can't tell, e.g. a finger bent towards or away from it).
function JointTable({ fit }: { fit: LiveFit }) {
  const s = fit.suggest;
  return (
    <>
      <table className="visual-cal-joints">
        <thead>
          <tr>
            <th>joint</th>
            <th>deg</th>
            <th>±</th>
            <th title="how much of the joint's motion this view shows">seen</th>
            <th>sure</th>
          </tr>
        </thead>
        <tbody>
          {fit.joint_table.map((j) => (
            <tr key={j.name} className={j.confidence}>
              <td>{j.name}</td>
              <td>{j.deg.toFixed(1)}</td>
              <td>
                {j.std_deg === null ? "–" : j.std_deg.toFixed(1)}
                {j.spread_deg !== null && j.spread_deg > 0
                  ? ` (${j.spread_deg.toFixed(0)})`
                  : ""}
              </td>
              <td>{Math.round(j.seen * 100)}%</td>
              <td
                title={
                  j.ambiguous
                    ? "fits about as well over this range (in brackets): this view can't tell"
                    : j.at_limit
                      ? "at its joint limit"
                      : ""
                }
              >
                {j.confidence}
                {j.ambiguous ? " ?" : ""}
                {j.at_limit ? " |" : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {s && (
        <span className={s.better ? "warn" : ""}>
          {s.better
            ? `Turn the plate to about ${s.angle.toFixed(0)}° to see ${s.joints.join(", ")} better (Keep view first to keep this one).`
            : `No plate angle shows ${s.joints.join(", ")} much better: keep views from two angles.`}
        </span>
      )}
    </>
  );
}

function ViewPanel({
  view,
  setView,
  keys,
}: {
  view: ViewSettings;
  setView: (v: ViewSettings) => void;
  keys: LayerKey[];
}) {
  const layer = (k: LayerKey, patch: Partial<LayerStyle>) =>
    setView({
      ...view,
      layers: { ...view.layers, [k]: { ...view.layers[k], ...patch } },
    });
  return (
    <div
      className="visual-cal-view"
      onClick={(e) => e.stopPropagation()}
      title=""
    >
      <button
        type="button"
        className="visual-cal-view-toggle"
        onClick={() => setView({ ...view, open: !view.open })}
      >
        View {view.open ? "▾" : "▸"}
      </button>
      {view.open && (
        <div className="visual-cal-view-body">
          <label className="visual-cal-view-row visual-cal-view-mode">
            <span>show</span>
            <select
              value={view.mode}
              onChange={(e) =>
                setView({ ...view, mode: e.target.value as ViewMode })
              }
            >
              {MODES.map(([m, label]) => (
                <option key={m} value={m}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="visual-cal-view-row">
            <span>image fade</span>
            <input
              type="range"
              min={0}
              max={80}
              value={Math.round(view.fade * 100)}
              onChange={(e) =>
                setView({ ...view, fade: Number(e.target.value) / 100 })
              }
            />
            <span className="visual-cal-view-val">
              {Math.round(view.fade * 100)}%
            </span>
          </label>
          {keys.map((k) => (
            <label key={k} className="visual-cal-view-row">
              <span>{LAYER_NAMES[k]}</span>
              <input
                type="color"
                value={view.layers[k].color}
                onChange={(e) => layer(k, { color: e.target.value })}
              />
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round(view.layers[k].opacity * 100)}
                onChange={(e) =>
                  layer(k, { opacity: Number(e.target.value) / 100 })
                }
              />
              <span className="visual-cal-view-val">
                {Math.round(view.layers[k].opacity * 100)}%
              </span>
            </label>
          ))}
          <button
            type="button"
            className="visual-cal-view-reset"
            onClick={() => setView({ ...DEFAULT_VIEW, open: true })}
          >
            defaults
          </button>
        </div>
      )}
    </div>
  );
}

function RotatedVideo({
  video,
  ready,
  rotation,
  overlay,
  layers,
  caption,
}: {
  video: RefObject<HTMLVideoElement | null>;
  ready: boolean;
  rotation: Rotation;
  overlay: Detected | null;
  layers: Layers;
  caption?: string; // shown over the enlarged view (the plate angle)
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  // Click: near full screen, click again or Esc to close. The same canvas, only its box
  // changes, and everything is drawn in its own pixels, so the overlay stays aligned.
  const [zoomed, setZoomed] = useState(false);
  useEffect(() => {
    if (!zoomed) return;
    const key = (e: KeyboardEvent) => e.key === "Escape" && setZoomed(false);
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [zoomed]);
  const [view, setViewState] = useState(loadView);
  const setView = (v: ViewSettings) => {
    setViewState(v);
    store(VIEW_KEY, v);
  };
  const viewRef = useRef(view);
  viewRef.current = view;
  const seg = view.mode === "seg" || view.mode === "seg-model";
  const urdf: LayerKey[] = layers.estimate ? ["estimate", "zero"] : ["cad", "fit"];
  const keys: LayerKey[] =
    view.mode === "camera"
      ? []
      : seg
        ? ["seg", "edges", ...(view.mode === "seg-model" ? urdf : [])]
        : layers.estimate
          ? urdf
          : [
            ...(layers.tiles ? (["tiles"] as const) : []),
            ...(layers.tiles || overlay ? (["detected"] as const) : []),
            ...(layers.hand ? (["hand"] as const) : []),
            ...(layers.fit ? (["cad", "fit"] as const) : []),
          ];
  // The fit's segmentation (hand mask 1, edges 2) as an image in the layer colours.
  const segImage = useRef<{ img: HTMLCanvasElement; box: number[] } | null>(
    null,
  );
  const segData = layers.fit?.segmentation;
  const segColors = JSON.stringify([view.layers.seg, view.layers.edges]);
  useEffect(() => {
    if (!segData) {
      segImage.current = null;
      return;
    }
    let alive = true;
    const im = new Image();
    im.onload = () => {
      if (!alive) return;
      const c = document.createElement("canvas");
      c.width = im.width;
      c.height = im.height;
      const x = c.getContext("2d");
      if (!x) return;
      x.drawImage(im, 0, 0);
      const d = x.getImageData(0, 0, c.width, c.height);
      const rgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
      const [fg, ed] = [rgb(view.layers.seg.color), rgb(view.layers.edges.color)];
      for (let i = 0; i < d.data.length; i += 4) {
        const v = d.data[i];
        const col = v === 2 ? ed : v === 1 ? fg : null;
        if (col) {
          d.data[i] = col[0];
          d.data[i + 1] = col[1];
          d.data[i + 2] = col[2];
        }
        d.data[i + 3] = Math.round(
          255 *
            (v === 2
              ? view.layers.edges.opacity
              : v === 1
                ? view.layers.seg.opacity
                : 0),
        );
      }
      x.putImageData(d, 0, 0);
      segImage.current = { img: c, box: segData.box };
    };
    im.src = `data:image/png;base64,${segData.png}`;
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segData, segColors]);
  const overlayRef = useRef(overlay);
  overlayRef.current = overlay;
  const layersRef = useRef(layers);
  layersRef.current = layers;
  useEffect(() => {
    if (!ready) return;
    let raf = 0;
    const draw = () => {
      const v = video.current;
      const c = canvas.current;
      const ctx = c?.getContext("2d");
      if (v && c && ctx && v.videoWidth) {
        const W = v.videoWidth;
        const H = v.videoHeight;
        const side = rotation === 90 || rotation === 270;
        const w = side ? H : W;
        const h = side ? W : H;
        if (c.width !== w || c.height !== h) {
          c.width = w;
          c.height = h;
        }
        const a = (rotation * Math.PI) / 180;
        ctx.setTransform(1, 0, 0, 1, w / 2, h / 2);
        ctx.rotate(a);
        const { fade, layers: style, mode } = viewRef.current;
        const segMode = mode === "seg" || mode === "seg-model";
        if (segMode) {
          ctx.fillStyle = "#000";
          ctx.fillRect(-W / 2, -H / 2, W, H);
          const sg = segImage.current;
          const f = layersRef.current.fit;
          if (sg && f) {
            const mx = W / f.size[0];
            const my = H / f.size[1];
            const [u, q, bw, bh] = sg.box;
            ctx.imageSmoothingEnabled = false;
            ctx.drawImage(sg.img, u * mx - W / 2, q * my - H / 2, bw * mx, bh * my);
            ctx.imageSmoothingEnabled = true;
          }
        } else ctx.drawImage(v, -W / 2, -H / 2);
        if (fade > 0 && !segMode) {
          ctx.save();
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.globalCompositeOperation = "saturation";
          ctx.globalAlpha = Math.min(1, fade * 1.25);
          ctx.fillStyle = "#808080";
          ctx.fillRect(0, 0, w, h);
          ctx.globalCompositeOperation = "source-over";
          ctx.globalAlpha = fade * 0.75;
          ctx.fillStyle = "#000";
          ctx.fillRect(0, 0, w, h);
          ctx.restore();
        }
        // Canvas pixels per screen pixel: lines and letters keep their on-screen size.
        const px = c.width / Math.max(1, c.clientWidth);
        const { model, tiles, hand, letters, estimate, zero, fit: est, target } =
          layersRef.current;
        const showOverlay = mode === "overlay";
        const urdfShown = showOverlay || mode === "seg-model";
        const k = Math.min(
          1,
          Math.max(0.1, (window.devicePixelRatio || 1) / px),
        );
        const drawHand = (
          h: HandOverlay,
          { color, opacity }: LayerStyle,
          pose: Record<string, number> | null,
          mount: number[][] | null,
        ) => {
          if (opacity <= 0) return;
          h.setColor(color);
          h.setPose(pose);
          h.setMount(mount);
          const img = h.render(Math.round(W * k), Math.round(H * k));
          ctx.globalAlpha = opacity;
          if (img) ctx.drawImage(img, -W / 2, -H / 2, W, H);
          ctx.globalAlpha = 1;
        };
        if (model && urdfShown && estimate) {
          const q = est?.joints_deg ?? null;
          if (zero && q)
            drawHand(
              zero,
              style.zero,
              Object.fromEntries(Object.keys(q).map((j) => [j, 0])),
              null,
            );
          drawHand(estimate, style.estimate, q, est?.plate_from_hand ?? null);
        }
        if (model && urdfShown && estimate && target)
          drawHand(estimate, style.estimate, target.pose, target.mount);
        if (model && showOverlay) {
          if (hand && !target) drawHand(hand, style.hand, null, null);
          if (tiles && style.tiles.opacity > 0)
            drawTiles(ctx, model, W, H, a, w, h, px, style.tiles, letters);
        }
        const fit = layersRef.current.fit;
        if (fit && !estimate && urdfShown) {
          const mx = W / fit.size[0];
          const my = H / fit.size[1];
          const line = (
            polys: [number, number][][],
            { color, opacity }: LayerStyle,
            dash: number[],
          ) => {
            ctx.strokeStyle = color;
            ctx.lineWidth = 2 * px;
            ctx.setLineDash(dash.map((d) => d * px));
            ctx.globalAlpha = opacity;
            for (const poly of polys) {
              ctx.beginPath();
              poly.forEach(([u, v], i) =>
                i
                  ? ctx.lineTo(u * mx - W / 2, v * my - H / 2)
                  : ctx.moveTo(u * mx - W / 2, v * my - H / 2),
              );
              ctx.closePath();
              ctx.stroke();
            }
            ctx.setLineDash([]);
            ctx.globalAlpha = 1;
          };
          line(fit.outlines.cad, style.cad, [6, 5]);
          line(fit.outlines.fit, style.fit, []);
        }
        const o = overlayRef.current;
        if (o && showOverlay && style.detected.opacity > 0) {
          const sx = W / o.size[0];
          const sy = H / o.size[1];
          const r = Math.max(4, W / 400);
          ctx.globalAlpha = style.detected.opacity;
          ctx.fillStyle = style.detected.color;
          for (const d of o.detections)
            for (const [u, q] of d.uv) {
              ctx.beginPath();
              ctx.arc(u * sx - W / 2, q * sy - H / 2, r, 0, 2 * Math.PI);
              ctx.fill();
            }
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.font = `700 ${Math.round(W / 60)}px 'Space Mono', monospace`;
          ctx.textAlign = "center";
          for (const d of o.detections) {
            const mu = d.uv.reduce((s, p) => s + p[0], 0) / d.uv.length;
            const mv = d.uv.reduce((s, p) => s + p[1], 0) / d.uv.length;
            const x = mu * sx - W / 2;
            const y = mv * sy - H / 2;
            const label = d.tile.replace("tile_", "").replace("_", " ");
            const px = w / 2 + x * Math.cos(a) - y * Math.sin(a);
            const py = h / 2 + x * Math.sin(a) + y * Math.cos(a);
            ctx.lineWidth = 6;
            ctx.strokeStyle = "rgba(0,0,0,0.7)";
            ctx.strokeText(label, px, py);
            ctx.fillText(label, px, py);
          }
          ctx.globalAlpha = 1;
        }
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [ready, rotation, video]);
  return (
    <div
      className={zoomed ? "visual-cal-zoom" : "visual-cal-frame"}
      onClick={() => setZoomed((z) => !z)}
      title={zoomed ? "Click or Esc to close" : "Click to enlarge"}
    >
      <canvas ref={canvas} className="visual-cal-video" />
      <ViewPanel view={view} setView={setView} keys={keys} />
      {zoomed && caption && (
        <span className="visual-cal-zoom-caption">{caption}</span>
      )}
      {seg && !segData && (
        <span className="visual-cal-seg-note">
          no segmentation yet: it comes with the pose estimate (Auto-solve)
        </span>
      )}
    </div>
  );
}

// Where the model comes from: the CAD before calibration, the solve after it.
function sourceText(m: ModelOverlay): string {
  const s = m.source;
  if (s.lens === "calibrated" && s.camera === "calibrated")
    return "calibrated 1a+1b";
  if (s.lens === "calibrated") return "lens from 1a, camera from CAD";
  return "CAD (not calibrated)";
}

function pickDefault(cameras: MediaDeviceInfo[]): string {
  const saved = stored<string>(CAMERA_KEY, "");
  if (saved && cameras.some((c) => c.deviceId === saved)) return saved;
  return (
    (cameras.find((c) => PREFERRED.test(c.label)) ?? cameras[0])?.deviceId ?? ""
  );
}

// Focus, exposure and white balance fixed at their current values, where the
// browser and camera allow it (Chrome over UVC does for the BRIO).
async function lockCamera(
  stream: MediaStream,
): Promise<{ locked: boolean; text: string }> {
  const track = stream.getVideoTracks()[0];
  const caps = (track.getCapabilities?.() ?? {}) as Record<string, unknown>;
  const now = track.getSettings() as Record<string, unknown>;
  const locks: Record<string, unknown> = {};
  const can = (key: string) =>
    Array.isArray(caps[key]) && (caps[key] as string[]).includes("manual");
  if (can("focusMode"))
    Object.assign(locks, {
      focusMode: "manual",
      ...(now.focusDistance !== undefined && {
        focusDistance: now.focusDistance,
      }),
    });
  if (can("exposureMode"))
    Object.assign(locks, {
      exposureMode: "manual",
      ...(now.exposureTime !== undefined && { exposureTime: now.exposureTime }),
    });
  if (can("whiteBalanceMode"))
    Object.assign(locks, {
      whiteBalanceMode: "manual",
      ...(now.colorTemperature !== undefined && {
        colorTemperature: now.colorTemperature,
      }),
    });
  const names = Object.keys(locks)
    .filter((k) => k.endsWith("Mode"))
    .map((k) => k.replace("Mode", ""));
  if (!names.length)
    return {
      locked: false,
      text: "this browser can’t lock this camera: lock it in Logi Tune",
    };
  await track.applyConstraints({
    advanced: [locks as MediaTrackConstraintSet],
  });
  return { locked: true, text: `locked: ${names.join(", ")}` };
}

function TurntableBar({
  tt,
  byHand,
  disabled,
  onConnect,
  onCalibrate,
  onRelease,
  onByHand,
}: {
  tt: Turntable | null;
  byHand: boolean;
  disabled: boolean;
  onConnect: () => void;
  onRelease: () => void;
  onCalibrate: () => void;
  onByHand: (on: boolean) => void;
}) {
  const state = byHand
    ? "turned by hand"
    : !tt?.connected
      ? "not connected"
      : tt.busy
        ? "moving…"
        : tt.homed
          ? `${tt.zero_from === "calibration" ? "calibrated" : "homed"} · ${tt.angle?.toFixed(1) ?? "?"}° · torque ${tt.torque ? "on" : "off"}`
          : "connected · not homed";
  const tone = byHand ? "" : !tt?.connected ? "off" : tt.homed ? "ok" : "warn";
  return (
    <div className="visual-cal-turntable">
      <span
        className={`visual-cal-chip ${tone}`}
        title={tt?.port ? `${tt.port} · motor ${tt.motor_id}` : undefined}
      >
        <i />
        turntable{tt?.mock && !byHand ? " (simulated)" : ""} · {state}
      </span>
      {!byHand &&
        (tt?.connected ? (
          <>
            <button
              className="btn btn-secondary btn-sm"
              onClick={onCalibrate}
              disabled={disabled}
              title="Find the hard stop (3×), the stop's other side and every stop's motor position; saved to turntable_calibration.yaml"
            >
              {tt.calibrated ? "Recalibrate motor" : "Calibrate motor"}
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={onRelease}
              disabled={disabled}
              title="Torque off and disconnect the motor"
            >
              Release
            </button>
          </>
        ) : (
          <button
            className="btn btn-secondary btn-sm"
            onClick={onConnect}
            disabled={disabled}
            title="Find the plate's Dynamixel and connect"
          >
            Connect
          </button>
        ))}
      <button
        className="visual-cal-link"
        onClick={() => onByHand(!byHand)}
        disabled={disabled}
      >
        {byHand ? "use the motor" : "no motor? turn by hand"}
      </button>
    </div>
  );
}

export function VisualCalibrationView() {
  const [cameras, setCameras] = useState<MediaDeviceInfo[]>([]);
  const [cameraId, setCameraId] = useState("");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [playing, setPlaying] = useState(false);
  const [size, setSize] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rotation, setRotation] = useState<Rotation>(() =>
    stored<Rotation>(ROTATION_KEY, 270),
  );
  // Auto: the backend reads the tower's up from the tiles in each live frame; a click on a turn overrides it.
  const [manualRotation, setManualRotation] = useState<boolean>(() =>
    stored<boolean>(ROTATION_MANUAL_KEY, false),
  );
  const manualRef = useRef(manualRotation);
  manualRef.current = manualRotation;
  const [stepId, setStepId] = useState<StepId>(() => {
    const s = stored<StepId>(STEP_KEY, "mount");
    return STEPS.some((d) => d.id === s) ? s : "mount";
  });
  const [confirmed, setConfirmed] = useState<StepId[]>(() =>
    stored<StepId[]>(CONFIRMED_KEY, []),
  );
  const [saved, setSaved] = useState<string[]>(() =>
    stored<string[]>(SAVED_KEY, []),
  );
  const [byHand, setByHand] = useState(() =>
    stored<boolean>(BY_HAND_KEY, false),
  );
  const [rig, setRig] = useState<RigInfo | null>(null);
  const [tt, setTt] = useState<Turntable | null>(null);
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [byKind, setByKind] = useState<Record<SessionKind, Session | null>>({
    camera: null,
    rotation: null,
    hand: null,
  });
  const [stopIdx, setStopIdx] = useState(0);
  const [picked, setPicked] = useState(false); // a stop chosen on the dial: Capture retakes it
  const [overlay, setOverlay] = useState<Detected | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [sweep, setSweep] = useState<{ i: number; n: number } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [issue, setIssue] = useState<Issue | null>(null);
  const [overlayOn, setOverlayOn] = useState<Partial<Record<StepId, boolean>>>(
    () => stored(OVERLAY_KEY, {}),
  );
  const [mountHand, setMountHand] = useState(() =>
    stored<boolean>(MOUNT_HAND_KEY, false),
  );
  const [model, setModel] = useState<ModelOverlay | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const [hand, setHand] = useState<HandOverlay | null>(null);
  const [handZero, setHandZero] = useState<HandOverlay | null>(null);
  const [sandboxPose, setSandboxPose] = useState<Record<string, number> | null>(null);
  const [sandboxMount, setSandboxMount] = useState<number[][] | null>(null);
  const [handNote, setHandNote] = useState<string | null>(null);
  const handInfo = useAppStore((s) => s.handInfo);
  const handState = useAppStore((s) => s.status?.state ?? null);
  const [fit, setFit] = useState<LiveFit | null>(null);
  const [fitRate, setFitRate] = useState<number | null>(null);
  const [solving, setSolving] = useState(false);
  const [solveJoints, setSolveJoints] = useState(() =>
    stored(SOLVE_JOINTS_KEY, true),
  );
  const solveJointsRef = useRef(solveJoints);
  solveJointsRef.current = solveJoints;
  const solvingRef = useRef(false);
  const handRef = useRef<HandOverlay | null>(null);
  const handZeroRef = useRef<HandOverlay | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const abort = useRef(false);
  const busyRef = useRef(false);
  busyRef.current = busy !== null || sweep !== null;

  const index = STEPS.findIndex((s) => s.id === stepId);
  const step = STEPS[index];
  const kind = step.sweep ?? null;
  const session = kind ? byKind[kind] : null;
  const stops = rig?.stops ?? [];
  const motorReady = !byHand && !!tt?.connected && tt.homed;

  // The stream stops while the tab is hidden (no decoding for nobody).
  const pageVisible = usePageVisible();

  // Labels are only readable once camera access is granted.
  useEffect(() => {
    let alive = true;
    const list = async () => {
      const all = (await navigator.mediaDevices.enumerateDevices()).filter(
        (d) => d.kind === "videoinput",
      );
      if (!alive) return;
      setCameras(all);
      setCameraId((id) =>
        id && all.some((c) => c.deviceId === id) ? id : pickDefault(all),
      );
    };
    // The access probe opens the camera at its default mode, which switches the device for
    // every client (the study's 4K capture too): only probe while labels are still hidden.
    navigator.mediaDevices
      .enumerateDevices()
      .then((all) =>
        all.some((d) => d.kind === "videoinput" && d.label)
          ? list()
          : navigator.mediaDevices.getUserMedia({ video: true }).then((probe) => {
              probe.getTracks().forEach((t) => t.stop());
              return list();
            }),
      )
      .catch((e: Error) => alive && setError(`No camera access: ${e.message}`));
    navigator.mediaDevices.addEventListener("devicechange", list);
    return () => {
      alive = false;
      navigator.mediaDevices.removeEventListener("devicechange", list);
    };
  }, []);

  useEffect(() => {
    if (!cameraId || !pageVisible) return;
    let opened: MediaStream | null = null;
    let alive = true;
    setSize(null);
    navigator.mediaDevices
      .getUserMedia({
        video: {
          deviceId: { exact: cameraId },
          width: { ideal: 3840 },
          height: { ideal: 2160 },
        },
      })
      .then((s) => {
        if (!alive) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        opened = s;
        setStream(s);
        setError(null);
        const st = s.getVideoTracks()[0]?.getSettings();
        if (st?.width)
          setSize(
            `${st.width}×${st.height}${st.frameRate ? ` · ${Math.round(st.frameRate)} fps` : ""}`,
          );
      })
      .catch(
        (e: Error) =>
          alive && setError(`Could not open the camera: ${e.message}`),
      );
    return () => {
      alive = false;
      opened?.getTracks().forEach((t) => t.stop());
      setStream(null);
    };
  }, [cameraId, pageVisible]);

  // One <video> for the whole page: every step captures from it.
  useEffect(() => {
    const v = video.current;
    setPlaying(false);
    if (!v || !stream) return;
    v.srcObject = stream;
    const on = () => setPlaying(true);
    v.addEventListener("loadeddata", on);
    void v.play().catch(() => undefined);
    return () => v.removeEventListener("loadeddata", on);
  }, [stream]);

  const refreshSessions = useCallback(async () => {
    const all = await visualApi.sessions();
    setSessions(all);
    return all;
  }, []);

  useEffect(() => {
    visualApi.rig().then(setRig, (e: Error) => setNote(e.message));
  }, []);
  // The motor can be moved from elsewhere (another tab, the CLI): its state on every step change.
  useEffect(() => {
    visualApi.turntable().then(setTt, () => undefined);
  }, [stepId]);

  // Each kind opens its latest session.
  useEffect(() => {
    let alive = true;
    refreshSessions()
      .then(async (all) => {
        const open = async (k: SessionKind) => {
          const latest = all.find((s) => s.step === k);
          return latest ? visualApi.session(latest.id) : null;
        };
        const [camera, rot, hand] = await Promise.all(KINDS.map(open));
        if (alive) setByKind({ camera, rotation: rot, hand });
      })
      .catch((e: Error) => alive && setNote(e.message));
    return () => {
      alive = false;
    };
  }, [refreshSessions]);

  // The first stop without a photo, when a session is opened or the step changes (not after each capture).
  useEffect(() => {
    if (!rig) return;
    const taken = new Set(session?.photos.map((p) => p.stop_deg));
    const next = rig.stops.findIndex((s) => !taken.has(s));
    setStopIdx(next < 0 ? 0 : next);
    setPicked(false);
  }, [rig, session?.id, kind]);

  const showResults = !!session?.result && !sweep && !picked;
  // Live tiles on a downscaled frame, only while the camera is on screen.
  const live = !!step.live && playing && !showResults;
  useEffect(() => {
    if (!live) {
      setOverlay(null);
      return;
    }
    let alive = true;
    let timer = 0;
    const tick = async () => {
      const v = video.current;
      if (alive && v?.videoWidth && !busyRef.current) {
        try {
          const found = await visualApi.detect(
            await grabFrame(v, "image/jpeg", 1600),
          );
          if (alive) setOverlay(found);
          const o = found.orientation;
          if (alive && o && o.agreement >= 0.9 && !manualRef.current) {
            store(ROTATION_KEY, o.rotation);
            setRotation(o.rotation);
          }
        } catch {
          /* next tick */
        }
      }
      if (alive) timer = window.setTimeout(tick, LIVE_MS);
    };
    timer = window.setTimeout(tick, LIVE_MS);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [live]);

  // The plate's read-back angle, ~5 Hz (also with the torque off): the overlay follows the plate.
  // On the hand steps the turntable is connected read-only (torque off) so the angle is known.
  const ttConnected = !!tt?.connected;
  useEffect(() => {
    if (!ttConnected) return;
    const off = () =>
      navigator.sendBeacon?.("/api/visual-calibration/turntable/torque-off");
    window.addEventListener("pagehide", off);
    return () => window.removeEventListener("pagehide", off);
  }, [ttConnected]);
  const autoConnected = useRef(false);
  useEffect(() => {
    if (
      byHand ||
      ttConnected ||
      autoConnected.current ||
      step.phase !== "hand" ||
      !step.live
    )
      return;
    autoConnected.current = true;
    visualApi.connect(false).then(setTt, () => undefined);
  }, [byHand, ttConnected, step.phase, step.live]);
  useEffect(() => {
    if (byHand || !ttConnected) return;
    const id = window.setInterval(() => {
      visualApi.turntable().then(
        (next) =>
          setTt((prev) =>
            prev &&
            prev.connected === next.connected &&
            prev.angle === next.angle &&
            prev.torque === next.torque &&
            prev.busy === next.busy &&
            prev.homed === next.homed
              ? prev
              : next,
          ),
        () => undefined,
      );
    }, 200);
    return () => window.clearInterval(id);
  }, [byHand, ttConnected]);

  // ---- the model overlay: tiles on the rig steps, the hand URDF on the hand steps (and on step 1 if asked)
  const overlayShown =
    !!step.live && !showResults && (overlayOn[step.id] ?? !!step.overlay);
  const tilesShown = overlayShown && step.phase === "rig";
  const handShown =
    overlayShown &&
    (step.phase === "hand" || (step.id === "mount" && mountHand));
  const motorAngle =
    !byHand && tt?.connected && tt.homed && tt.angle !== null ? tt.angle : null;
  const plateAngle =
    Math.round(
      10 *
        (motorAngle ??
          (byHand && kind && stops.length
            ? stops[stopIdx]
            : ((step.phase === "hand" ? rig?.swap_angle : rig?.side0_stop) ??
              180))),
    ) / 10;
  const plateAngleRef = useRef(plateAngle);
  plateAngleRef.current = plateAngle;

  useEffect(() => {
    if (!overlayShown || !playing) return;
    let alive = true;
    visualApi.overlay(plateAngle, rotation).then(
      (m) => {
        if (!alive) return;
        setModel(m);
        setModelError(null);
      },
      (e: Error) => alive && setModelError(e.message),
    );
    return () => {
      alive = false;
    };
  }, [overlayShown, playing, plateAngle, rotation]);

  // The hand model loads once, the first time it is wanted, and stays for the page's life.
  const joints = handInfo?.joints;
  const wantHand = handShown && !hand;
  useEffect(() => {
    if (!wantHand) return;
    if (!joints) {
      setHandNote("no hand session: connect the hand to draw it");
      return;
    }
    let alive = true;
    setHandNote("loading the hand model…");
    const accent =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--accent")
        .trim() || "#22d3ee";
    Promise.all([api.modelMetadata(), import("./handOverlay")])
      .then(([meta, mod]) =>
        mod.HandOverlay.create(meta.urdf_url, joints, accent),
      )
      .then((h) => {
        if (!alive) return h.dispose();
        handRef.current = h;
        setHand(h);
        setHandNote(null);
      })
      .catch((e: Error) => alive && setHandNote(`no hand model: ${e.message}`));
    return () => {
      alive = false;
    };
  }, [wantHand, joints]);
  useEffect(() => () => handRef.current?.dispose(), []);
  // A second hand on the pose step: the URDF at zero on the CAD mount, to compare with.
  const wantZero = handShown && step.id === "hand-pose" && !!hand && !handZero;
  useEffect(() => {
    if (!wantZero || !joints) return;
    let alive = true;
    Promise.all([api.modelMetadata(), import("./handOverlay")])
      .then(([meta, mod]) => mod.HandOverlay.create(meta.urdf_url, joints, "#f59e0b"))
      .then((h) => {
        if (!alive) return h.dispose();
        handZeroRef.current = h;
        setHandZero(h);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [wantZero, joints]);
  useEffect(() => () => handZeroRef.current?.dispose(), []);
  useEffect(() => {
    if (hand && model) hand.place(model);
    if (handZero && model) handZero.place(model);
  }, [hand, handZero, model]);

  const toggleOverlay = (on: boolean) =>
    setOverlayOn((o) => {
      const next = { ...o, [step.id]: on };
      store(OVERLAY_KEY, next);
      return next;
    });
  const toggleMountHand = (on: boolean) => {
    store(MOUNT_HAND_KEY, on);
    setMountHand(on);
  };

  const say = (text: string | null, bad = false) => {
    setNote(text);
    setFailed(bad);
  };

  const run = async (label: string, job: () => Promise<void>) => {
    setBusy(label);
    say(null);
    try {
      await job();
    } catch (e) {
      say((e as Error).message, true);
    } finally {
      setBusy(null);
    }
  };

  const setSession = (k: SessionKind, s: Session | null) =>
    setByKind((b) => ({ ...b, [k]: s }));
  const confirm = (id: StepId) =>
    setConfirmed((c) => {
      if (c.includes(id)) return c;
      const next = [...c, id];
      store(CONFIRMED_KEY, next);
      return next;
    });

  const connect = () =>
    run("connecting…", async () => {
      setTt(await visualApi.connect());
    });
  const calibrateMotor = () =>
    run("calibrating the motor…", async () => {
      const r = await visualApi.calibrateMotor();
      setTt(r);
      const c = r.calibration;
      say(
        `Motor calibrated: travel ${c.travel_deg.toFixed(1)}° (${c.travel_error_deg >= 0 ? "+" : ""}${c.travel_error_deg.toFixed(1)}° from the design), the stop repeats within ${c.homing_spread_deg.toFixed(2)}°.`,
      );
    });
  const release = () =>
    run("releasing…", async () => {
      setTt(await visualApi.release());
    });
  const parkForSwap = () =>
    run("parking for the swap…", async () => {
      if (!rig) return;
      if (!tt?.connected) setTt(await visualApi.connect());
      setTt(await visualApi.move(rig.swap_angle));
      setTt(await visualApi.torqueOff());
      confirm("swap");
      say(
        `parked at ${rig.swap_angle}°, torque off: the plate turns by hand, the overlay follows it. Swap now.`,
      );
    });
  const nextStop = () =>
    run("turning…", async () => {
      if (!rig) return;
      if (!tt?.connected) setTt(await visualApi.connect());
      const at = tt?.angle ?? -1;
      const next = rig.stops.find((a) => a > at + 0.5) ?? rig.stops[0];
      setTt(await visualApi.move(next));
      say(`at ${next}°: compare the overlay`);
    });
  // The hand's joint angles for the debug fit: live from the hand session, else zeros (and why).
  const jointPose = (): { q: Record<string, number>; source: string } => {
    const st = useAppStore.getState().status;
    if (!st || (st.state !== "connected" && st.state !== "degraded"))
      return { q: {}, source: "zeros: hand not connected" };
    const j = latest.joints;
    if (st.capabilities?.encoders && Object.keys(j.measured).length)
      return { q: j.measured, source: "encoders" };
    if (Object.keys(j.estimate).length)
      return { q: j.estimate, source: "motor estimate" };
    return {
      q: {},
      source: "zeros: no joint angles (motor calibration incomplete)",
    };
  };
  const autoSolve = async () => {
    if (solvingRef.current) {
      solvingRef.current = false;
      return;
    }
    solvingRef.current = true;
    setSolving(true);
    say(null);
    let n = 0;
    const t0 = performance.now();
    try {
      while (solvingRef.current) {
        const v = video.current;
        if (!v?.videoWidth) throw new Error("no camera image");
        const { q, source } = jointPose();
        const r = await visualApi.liveFit(
          await grabFrame(v, "image/jpeg", 960),
          plateAngleRef.current,
          q,
          source,
          solveJointsRef.current,
          n % SEARCH_EVERY === 0,
        );
        setFit(r);
        n += 1;
        setFitRate((n * 1000) / (performance.now() - t0));
      }
    } catch (e) {
      say((e as Error).message, true);
    } finally {
      solvingRef.current = false;
      setSolving(false);
    }
  };
  const freezeFit = () =>
    run("saving…", async () => {
      const r = await visualApi.liveFitFreeze();
      say(`saved to ${r.path}`);
    });
  const resetFit = () =>
    run("resetting…", async () => {
      await visualApi.liveFitReset();
      await visualApi.liveFitClearViews();
      setFit(null);
    });
  const keepView = () =>
    run("keeping…", async () => {
      const r = await visualApi.liveFitKeepView();
      say(
        `view at ${plateAngle}° kept (${r.views} kept): turn the plate to another angle, keep the hand still`,
      );
    });
  const clearViews = () =>
    run("clearing…", async () => {
      await visualApi.liveFitClearViews();
      say("kept views cleared");
    });
  const toggleSolveJoints = (on: boolean) => {
    store(SOLVE_JOINTS_KEY, on);
    setSolveJoints(on);
  };
  const chooseByHand = (on: boolean) => {
    store(BY_HAND_KEY, on);
    setByHand(on);
  };

  // One photo at the selected stop into the step's session (made if there is none).
  const shoot = async (
    k: SessionKind,
    stop: number,
    s: Session | null,
  ): Promise<Session> => {
    const v = video.current;
    if (!v?.videoWidth) throw new Error("no camera image");
    const target = s ?? (await visualApi.createSession(k, byHand));
    const r = await visualApi.addPhoto(
      target.id,
      stop,
      await grabFrame(v, "image/png"),
    );
    setOverlay(r);
    const photos = [
      ...target.photos.filter((p) => p.stop_deg !== stop),
      r.photo,
    ].sort((a, b) => a.stop_deg - b.stop_deg);
    const next = { ...target, photos };
    setSession(k, next);
    return next;
  };

  // The motor homes into the hard stop, then turns to every stop; one photo at each.
  const runSweep = async () => {
    if (!kind || !rig) return;
    abort.current = false;
    setIssue(null);
    say(null);
    setPicked(false);
    setSweep({ i: 0, n: rig.stops.length });
    try {
      setNote("camera controls…");
      await visualApi.cameraSet().catch((e: Error) => {
        throw new Error(`camera check: ${e.message} (close Logi Tune)`);
      });
      if (!tt?.connected) setTt(await visualApi.connect());
      let s = await visualApi.createSession(kind, false);
      setSession(kind, s);
      setNote("homing…");
      setTt(await visualApi.home(true));
      for (let i = 0; i < rig.stops.length && !abort.current; i++) {
        const stop = rig.stops[i];
        setStopIdx(i);
        setSweep({ i, n: rig.stops.length });
        setNote(`${stop}°`);
        setTt(await visualApi.move(stop, true));
        s = await shoot(kind, stop, s);
      }
      setSession(kind, await visualApi.session(s.id));
      say(
        abort.current
          ? `stopped after ${s.photos.length} photos`
          : `${s.photos.length} photos`,
      );
      await refreshSessions();
    } catch (e) {
      say((e as Error).message, true);
    } finally {
      // Stopped, finished or failed: the torque goes off.
      await visualApi.torqueOff().then(setTt, () =>
        visualApi.turntable().then(setTt, () => undefined),
      );
      setSweep(null);
    }
  };

  const capture = () =>
    run("capturing…", async () => {
      if (!kind || !rig) return;
      const stop = rig.stops[stopIdx];
      const controls = await visualApi.cameraCheck().then(
        () => null,
        (e: Error) => e.message,
      );
      const held = motorReady && Math.abs((tt?.angle ?? -1) - stop) > 0.5;
      if (held) setTt(await visualApi.move(stop, true));
      const s = await shoot(kind, stop, session).finally(
        () => held && visualApi.torqueOff().then(setTt, () => undefined),
      );
      const p = s.photos.find((x) => x.stop_deg === stop);
      const taken = new Set(s.photos.map((x) => x.stop_deg));
      const next = rig.stops.findIndex((x, i) => i > stopIdx && !taken.has(x));
      if (byHand && next >= 0) setStopIdx(next);
      setPicked(false);
      say(
        controls
          ? `camera controls differ: ${controls} — close Logi Tune; a sweep sets them`
          : p
            ? `${stop}°: ${p.tiles} tiles, ${p.corners} corners`
            : null,
        !!controls,
      );
      await refreshSessions();
    });

  const pick = (i: number) => {
    setStopIdx(i);
    setPicked(true);
    if (motorReady && rig)
      void run("moving…", async () => {
        setTt(await visualApi.move(rig.stops[i]));
      });
  };

  const solve = () =>
    run("solving…", async () => {
      if (!session || !kind) return;
      setIssue(null);
      try {
        setSession(kind, await visualApi.solve(session.id));
      } catch (e) {
        const found = issueOf((e as Error).message);
        if (found.fix) {
          setIssue(found);
          return;
        }
        throw e;
      }
      setPicked(false);
      await refreshSessions();
    });

  const apply = () =>
    run("saving…", async () => {
      if (!session) return;
      const r = await visualApi.apply(session.id);
      const next = [...saved, session.id];
      setSaved(next);
      store(SAVED_KEY, next);
      say(`saved to ${r.path}`);
    });

  const lock = () =>
    run("locking…", async () => {
      if (!stream) return;
      const r = await lockCamera(stream);
      if (r.locked) confirm("camera");
      say(r.text, !r.locked);
    });

  const go = (i: number) => {
    const next = STEPS[Math.max(0, Math.min(STEPS.length - 1, i))];
    store(STEP_KEY, next.id);
    setStepId(next.id);
    say(null);
    setIssue(null);
  };
  const forward = () => {
    confirm(step.id);
    go(index + 1);
  };

  const openSession = (id: string) =>
    run("loading…", async () => {
      if (kind) setSession(kind, id ? await visualApi.session(id) : null);
    });

  const rotate = (r: Rotation | "auto") => {
    const manual = r !== "auto";
    store(ROTATION_MANUAL_KEY, manual);
    setManualRotation(manual);
    if (manual) {
      store(ROTATION_KEY, r);
      setRotation(r);
    }
  };
  const choose = (id: string) => {
    store(CAMERA_KEY, id);
    setCameraId(id);
  };

  // ---- step states, from the sessions where they can tell
  const photos = (k: SessionKind) => byKind[k]?.photos ?? [];
  const count = (k: SessionKind) =>
    new Set(photos(k).map((x) => x.stop_deg)).size;
  const weak = (k: SessionKind) =>
    photos(k).filter((x) => x.corners < WEAK).length;
  const begun = count("camera") > 0 || count("rotation") > 0;
  const cameraSolved = sessions.some((s) => s.step === "camera" && s.solved);
  const status = (s: StepDef): { state: StepState; note: string } => {
    const seen = confirmed.includes(s.id);
    switch (s.id) {
      case "mount":
        return {
          state: seen || begun ? "done" : "todo",
          note: `side 0 at ${rig?.side0_stop ?? 180}°`,
        };
      case "camera":
        return {
          state: seen || begun ? "done" : "todo",
          note: seen ? "locked" : "on its side · 65°",
        };
      case "light":
        return {
          state: seen || begun ? "done" : "todo",
          note: "even, no glare",
        };
      case "lens":
      case "rotation": {
        const k = s.sweep!;
        const sess = byKind[k];
        const r = sess?.result;
        const fit = r && fitOf(r);
        const isSaved = !!sess && saved.includes(sess.id);
        if (s.id === "rotation" && !cameraSolved && !count("rotation"))
          return { state: "todo", note: "after 1a" };
        if (fit)
          return {
            state: solvedWell(sess) ? "done" : "warn",
            note: `${fit.reprojection_px.toFixed(2)} px${isSaved ? " · saved" : ""}`,
          };
        if (!stops.length) return { state: "todo", note: "" };
        return {
          state: weak(k) ? "warn" : "todo",
          note: count(k)
            ? `${count(k)} / ${stops.length} stops · not solved`
            : "motor sweep",
        };
      }
      case "swap":
        return {
          state: seen || count("hand") > 0 ? "done" : "todo",
          note: "camera untouched",
        };
      case "hand-board":
        return {
          state: seen || handState === "connected" ? "done" : "todo",
          note: handState ?? "the hand's board",
        };
      case "hand-pose":
        return {
          state: fit ? "done" : "todo",
          note: fit
            ? fit.solve_joints
              ? `${fit.joint_table.filter((j) => j.confidence !== "poor").length} / ${fit.joint_table.length} joints`
              : "mount only"
            : "camera only",
        };
      case "hand-check":
        return { state: seen ? "done" : "todo", note: "by eye" };
      case "hand-control":
        return { state: seen ? "done" : "todo", note: "lookup table" };
      case "hand-capture": {
        if (!stops.length) return { state: "todo", note: "" };
        const n = count("hand");
        return {
          state: weak("hand") ? "warn" : n >= stops.length ? "done" : "todo",
          note: `${n} / ${stops.length} stops`,
        };
      }
    }
  };
  const states = STEPS.map(status);

  // ---- the step's controls: one primary at a time
  const taken = new Map(session?.photos.map((p) => [p.stop_deg, p]));
  const n = taken.size;
  const complete = stops.length > 0 && n >= stops.length;
  const solved = !!session?.result;
  const stopLabel = stops.length ? `${stops[stopIdx]}°` : "";
  const actions: Action[] = [];
  if (sweep) {
    actions.push({
      label: "Stop",
      title: "Stop after the current stop",
      onClick: () => (abort.current = true),
      primary: false,
    });
  } else if (step.id === "swap") {
    actions.push({
      label: "Park for the swap",
      title: `Turn the plate to ${rig?.swap_angle ?? 180}° and release the torque`,
      onClick: parkForSwap,
      primary: !confirmed.includes("swap"),
      disabled: !rig || byHand,
    });
  } else if (step.id === "hand-pose") {
    actions.push({
      label: solving ? "Stop" : "Auto-solve",
      title: "Estimate the hand's pose frame after frame, as fast as it goes",
      onClick: () => void autoSolve(),
      primary: true,
      disabled: !playing,
    });
    actions.push({
      label: "Keep view",
      title:
        "Keep this frame as an extra view of the same pose: then turn the plate to another angle",
      onClick: keepView,
      primary: false,
      disabled: !fit,
    });
    actions.push({
      label: "Clear views",
      title: "Drop the kept views",
      onClick: clearViews,
      primary: false,
      disabled: !fit?.views.length,
    });
    actions.push({
      label: "Freeze",
      title: "Save this frame and the estimate (offline debugging)",
      onClick: freezeFit,
      primary: false,
      disabled: !fit,
    });
    actions.push({
      label: "Reset",
      title: "Start again from the CAD hand at zero, without kept views",
      onClick: resetFit,
      primary: false,
      disabled: solving,
    });
  } else if (step.id === "hand-check") {
    actions.push({
      label: "Next stop",
      title: "Turn the plate to the next stop (from the hard-stop side)",
      onClick: nextStop,
      primary: false,
      disabled: !rig || byHand || !tt?.homed,
    });
  } else if (step.id === "camera") {
    actions.push({
      label: "Lock focus & exposure",
      title: "Fix focus, exposure and white balance at their current values",
      onClick: lock,
      primary: !confirmed.includes("camera"),
      disabled: !stream,
    });
  } else if (kind) {
    if (byHand)
      actions.push({
        label: `${taken.has(stops[stopIdx]) ? "Retake" : "Capture"} ${stopLabel}`,
        title: "Turn the plate to this stop by hand, then save a photo (Space)",
        onClick: capture,
        primary: !complete,
        disabled: !playing,
        key: "␣",
      });
    else {
      actions.push({
        label: n ? "Run again" : "Run sweep",
        title:
          "Home the motor into the hard stop, then a photo at every stop (a new session)",
        onClick: () => void runSweep(),
        primary: !complete,
        disabled: !playing || !rig,
      });
      if (picked && session)
        actions.push({
          label: `Retake ${stopLabel}`,
          title: "Replace the photo at this stop (Space)",
          onClick: capture,
          primary: false,
          disabled: !playing || !motorReady,
          key: "␣",
        });
    }
    if (step.solve && n >= 3 && (!solved || picked))
      actions.push({
        label: solved ? "Solve again" : "Solve",
        title:
          step.id === "lens"
            ? "Fit the lens and the tile poses to the photos"
            : "Fit the camera pose, the axis and every stop angle, from the camera step",
        onClick: solve,
        primary: complete || byHand,
      });
    if (
      step.solve &&
      solved &&
      solvedWell(session) &&
      !saved.includes(session!.id)
    )
      actions.push({
        label: "Save to rig",
        title:
          step.id === "lens"
            ? "Optional: the rotation step saves the lens too"
            : "Write camera, axis, stops, lens and tile poses to the rig calibration",
        onClick: apply,
        primary: step.id === "rotation",
      });
  }
  const last = index === STEPS.length - 1;
  const nextPrimary = !actions.some((a) => a.primary);

  // Space captures by hand or retakes, ← → move between steps (when no control has focus).
  const keys = useRef({ capture, go, forward, index, actions });
  keys.current = { capture, go, forward, index, actions };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        e.repeat ||
        document.activeElement !== document.body ||
        busyRef.current
      )
        return;
      const k = keys.current;
      if (e.code === "Space" && k.actions.some((a) => a.key)) {
        e.preventDefault();
        void k.capture();
      } else if (e.code === "ArrowRight" && k.index < STEPS.length - 1) {
        k.forward();
      } else if (e.code === "ArrowLeft") {
        k.go(k.index - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const kindSessions = sessions.filter((s) => s.step === kind);
  const working = busy !== null || sweep !== null;
  const dial = rig && kind && (
    <StopDial
      stops={rig.stops}
      travel={rig.travel}
      side0Stop={rig.side0_stop ?? 180}
      taken={taken}
      current={stopIdx}
      angle={!byHand && tt?.connected && tt.angle !== null ? tt.angle : null}
      onPick={working ? undefined : pick}
      object={step.phase === "rig"}
      corrections={
        step.id === "rotation" ? session?.result?.stop_angle_corrections : null
      }
    />
  );
  const camera =
    step.live &&
    !showResults &&
    (error ? (
      <p className="visual-cal-empty warn">{error}</p>
    ) : !stream ? (
      <p className="visual-cal-empty">
        {cameras.length ? "opening the camera…" : "looking for cameras…"}
      </p>
    ) : (
      <RotatedVideo
        video={video}
        ready={playing}
        rotation={rotation}
        overlay={overlay}
        layers={{
          model: overlayShown ? model : null,
          tiles: tilesShown,
          hand: handShown && step.id !== "hand-pose" ? hand : null,
          letters: rig?.letters ?? {},
          fit: step.id === "hand-pose" ? fit : null,
          estimate: handShown && (step.id === "hand-pose" || step.id === "hand-control") ? hand : null,
          target: step.id === "hand-control" && sandboxPose ? { pose: sandboxPose, mount: sandboxMount } : null,
          zero: handShown && step.id === "hand-pose" ? handZero : null,
        }}
        caption={`plate ${plateAngle}°${motorAngle === null ? " (assumed)" : tt?.torque ? "" : " (read-back, torque off)"}${overlayShown ? "" : " · overlay off"}`}
      />
    ));
  const calibrated =
    model?.source.lens === "calibrated" && model.source.camera === "calibrated";
  const hint =
    (step.phase === "rig"
      ? "Lines sit on the tiles when the rig is right. A whole side off before calibrating: the object sits another way round (the calibration finds it). All off by the same amount: the camera mount setting."
      : "Tower and forearm sit on the hand when the rig is right; the fingers follow the joint angles. All off by the same amount: the camera mount setting.") +
    (model && !calibrated ? " Before 1a and 1b, a few mm is normal." : "");
  const overlayBar = step.live && !showResults && stream && (
    <div className="visual-cal-overlay">
      <div className="toolbar">
        <label
          className="toggle-label"
          title="Draw the model over the camera image, as the rig config says the camera should see it"
        >
          <input
            type="checkbox"
            checked={overlayOn[step.id] ?? !!step.overlay}
            onChange={(e) => toggleOverlay(e.target.checked)}
          />
          overlay
        </label>
        {step.id === "mount" && (
          <label
            className="toggle-label"
            title="Also draw the hand, posed by its joint angles"
          >
            <input
              type="checkbox"
              checked={mountHand}
              disabled={!overlayShown}
              onChange={(e) => toggleMountHand(e.target.checked)}
            />
            hand
          </label>
        )}
      </div>
      {overlayShown && (
        <span
          className={`visual-cal-overlay-source${modelError ? " warn" : ""}`}
        >
          {modelError
            ? `model: ${modelError}`
            : model
              ? `model: ${sourceText(model)} · plate ${plateAngle}°${motorAngle === null ? " (assumed: turntable not connected)" : tt?.torque ? " (motor)" : " (read-back, torque off)"}`
              : "model: loading…"}
          {handShown && handNote ? ` · ${handNote}` : ""}
        </span>
      )}
    </div>
  );

  return (
    <>
      <SetupTabs />
      <section className="panel visual-cal">
        <video
          ref={video}
          className="visual-cal-source"
          autoPlay
          playsInline
          muted
        />
        <nav className="gt-steps visual-cal-nav">
          {STEPS.map((s, i) => (
            <div key={s.id} className="visual-cal-nav-item">
              {(i === 0 || STEPS[i - 1].phase !== s.phase) && (
                <div className="visual-cal-phase">{s.phase}</div>
              )}
              <button
                type="button"
                className={`gt-step jump visual-cal-step ${states[i].state}${i === index ? " active" : ""}`}
                title={`Go to ${s.title.toLowerCase()}`}
                onClick={() => go(i)}
              >
                <span className="gt-step-num">
                  {states[i].state === "done"
                    ? "✓"
                    : states[i].state === "warn"
                      ? "!"
                      : i + 1}
                </span>
                <span>
                  <div className="gt-step-title">
                    {s.title}
                    {s.tag && <span className="visual-cal-tag">{s.tag}</span>}
                  </div>
                  <div className="gt-step-note">{states[i].note}</div>
                </span>
              </button>
            </div>
          ))}
          {kind && (
            <div
              className="visual-cal-session"
              title={`Photos and solve of the ${kind} step`}
            >
              <select
                value={session?.id ?? ""}
                onChange={(e) => openSession(e.target.value)}
                disabled={working}
              >
                <option value="">no {kind} session</option>
                {kindSessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.id} · {s.photos}
                    {s.solved ? " · solved" : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
        </nav>

        <div className="visual-cal-content">
          <div className="visual-cal-side">
            <div className="visual-cal-head">
              <span className="visual-cal-count">
                {index + 1} / {STEPS.length} · {step.phase}
                {step.tag ? ` · ${step.tag}` : ""}
              </span>
              <h3 className="gt-heading">{step.title}</h3>
              <p className="setup-copy">{step.copy(rig)}</p>
              {step.items && (
                <ol className="setup-copy visual-cal-items">
                  {step.items(rig).map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ol>
              )}
            </div>
            {step.id === "hand-board" && <HandBoard rig={rig} />}
            {step.id === "hand-control" && (
              <ControlSandbox
                onTarget={(pose, mount) => {
                  setSandboxPose(pose);
                  setSandboxMount(mount);
                }}
              />
            )}
            {step.id === "hand-pose" && (
              <div
                className="visual-cal-hint"
                style={{ display: "grid", gap: 4 }}
              >
                <label className="toggle-label">
                  <input
                    type="checkbox"
                    checked={solveJoints}
                    onChange={(e) => toggleSolveJoints(e.target.checked)}
                  />
                  solve joints (vision)
                </label>
                {fit ? (
                  <>
                    <span>
                      mount Δ:{" "}
                      {fit.delta.translation_mm
                        .map((v) => v.toFixed(1))
                        .join(", ")}{" "}
                      mm ·{" "}
                      {fit.delta.rotation_deg
                        .map((v) => v.toFixed(1))
                        .join(", ")}
                      ° (plate x, y, z)
                    </span>
                    <span>
                      silhouette misfit: CAD {fit.cost_px.cad.toFixed(1)} px →
                      fit {fit.cost_px.fit.toFixed(1)} px
                      {fit.views.length
                        ? ` · views kept at ${fit.views.map((a) => `${a.toFixed(0)}°`).join(", ")}`
                        : ""}
                    </span>
                    <span>
                      {fitRate ? `${fitRate.toFixed(1)} solves/s` : ""} ·{" "}
                      {fit.iterations} it · {(fit.seconds * 1000).toFixed(0)} ms
                      · plate {fit.angle.toFixed(1)}°
                    </span>
                    {fit.solve_joints ? (
                      <JointTable fit={fit} />
                    ) : (
                      <span
                        className={
                          fit.joints_source.startsWith("zeros") ? "warn" : ""
                        }
                      >
                        joints: {fit.joints_source}
                        {fit.joints_used.length
                          ? ` (${fit.joints_used.length} used)`
                          : ""}
                        {fit.joints_unknown.length
                          ? ` · not in the model: ${fit.joints_unknown.join(", ")}`
                          : ""}
                      </span>
                    )}
                  </>
                ) : (
                  <span>
                    Auto-solve: the CAD hand is drawn at the estimate (View: colours, the CAD hand at zero)
                  </span>
                )}
              </div>
            )}

            {(kind || overlayBar) && (
              <div className="visual-cal-controls">
                {kind && (
                  <TurntableBar
                    tt={tt}
                    byHand={byHand}
                    disabled={working}
                    onConnect={connect}
                    onCalibrate={calibrateMotor}
                    onRelease={release}
                    onByHand={chooseByHand}
                  />
                )}
                {overlayBar}
              </div>
            )}
            {overlayShown && stream && (
              <p className="visual-cal-hint">{hint}</p>
            )}

            {issue && (
              <div className="gt-warning visual-cal-issue">
                <b>{issue.text}</b>
                {issue.fix === "camera-step" && (
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => go(STEPS.findIndex((s) => s.id === "lens"))}
                  >
                    ← Calibrate the camera
                  </button>
                )}
                {issue.fix === "mount" && (
                  <span>
                    The camera mount in the rig config (camera › mount:{" "}
                    {rig?.camera_mount
                      ? `${rig.camera_mount.distance} mm, ${rig.camera_mount.height} mm, ${rig.camera_mount.tilt}°`
                      : "not set"}
                    ) does not match this rig, or the camera moved. Fix the
                    setting, then solve again.
                  </span>
                )}
              </div>
            )}

            {(step.art || dial) && (
              <div className="visual-cal-stage">
                {step.art && <StepArt art={step.art} />}
                {dial}
              </div>
            )}

            {step.id === "camera" && (
              <div className="visual-cal-toolbar">
                <select
                  value={cameraId}
                  onChange={(e) => choose(e.target.value)}
                  disabled={!cameras.length}
                  title="Camera"
                >
                  {cameras.map((c, i) => (
                    <option key={c.deviceId} value={c.deviceId}>
                      {c.label || `camera ${i + 1}`}
                    </option>
                  ))}
                </select>
                <div
                  className="view-tabs"
                  title="Turn the image: auto reads the tower's up from the tiles; a turn overrides it"
                >
                  <button
                    className={`view-tab ${manualRotation ? "" : "active"}`}
                    onClick={() => rotate("auto")}
                  >
                    auto
                  </button>
                  {ROTATIONS.map((r) => (
                    <button
                      key={r}
                      className={`view-tab ${manualRotation && rotation === r ? "active" : ""}`}
                      onClick={() => rotate(r)}
                    >
                      {r}°
                    </button>
                  ))}
                </div>
                {size && <span className="setup-card-hint">{size}</span>}
              </div>
            )}

            <div className="gt-actions visual-cal-actions">
              {sweep && (
                <div
                  className="setup-progress visual-cal-progress"
                  title={`stop ${sweep.i + 1} of ${sweep.n}`}
                >
                  <div
                    className="setup-progress-fill"
                    style={{ width: `${((sweep.i + 1) / sweep.n) * 100}%` }}
                  />
                </div>
              )}
              <span
                className={`visual-cal-note${failed && !busy ? " warn" : ""}`}
              >
                {sweep
                  ? `sweep ${sweep.i + 1} / ${sweep.n} · ${note ?? ""}`
                  : (busy ?? note)}
              </span>
              <button
                className="btn btn-secondary"
                onClick={() => go(index - 1)}
                disabled={index === 0 || !!sweep}
                title="Previous step (←)"
              >
                ← Back
              </button>
              {actions.map((a) => (
                <button
                  key={a.label}
                  className={`btn ${a.primary ? "btn-primary" : "btn-secondary"}`}
                  onClick={a.onClick}
                  disabled={
                    busy !== null ||
                    (sweep !== null && a.label !== "Stop") ||
                    a.disabled
                  }
                  title={a.title}
                >
                  {a.label}
                  {a.key && <span className="gt-key">{a.key}</span>}
                </button>
              ))}
              {!last && (
                <button
                  className={`btn ${nextPrimary ? "btn-primary" : "btn-secondary"}`}
                  onClick={forward}
                  disabled={!!sweep}
                  title="Done: next step (→)"
                >
                  Next →
                </button>
              )}
            </div>
          </div>
          <div className="visual-cal-main">
            {camera && <div className="visual-cal-live">{camera}</div>}
            {showResults && session && (
              <Results session={session} cad={rig?.camera_mount ?? null} />
            )}
          </div>
        </div>
      </section>
    </>
  );
}
