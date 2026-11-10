// Accurate control sandbox: drive the hand to the joint angles you want, through the hand
// study's lookup table (orca_core experiments/visual_calibration/hand_study) or straight
// (orca_core's linear map), and test whether the thumb really touches each fingertip.
// The tactile fingertips tell: both pads must feel the contact.

import { useEffect, useRef, useState } from "react";
import { useStreamFrame } from "../../hooks/useStreamFrame";
import { latest } from "../../state/streamStore";
import { useAppStore } from "../../state/appStore";
import { useStudyMap } from "../../state/studyMapStore";
import { visualApi, type LutCommand, type LutState } from "./api";

const RAMP_DEG_S = 30;
const HZ = 20;
const TOUCH_N = 0.3; // both pads above this (after zeroing): a touch
const FINGERS = ["index", "middle", "ring", "pinky"] as const;
type Mode = "standard" | "lut";
type Result = { thumb: number; finger: number } | null;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function post(path: string, body: unknown = {}) {
  const r = await fetch("/api" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail ?? r.statusText);
  }
  return r.json();
}

export function ControlSandbox({
  onTarget,
}: {
  onTarget: (pose: Record<string, number> | null, mount: number[][] | null) => void;
}) {
  const joints = useAppStore((s) => s.handInfo?.joints) ?? [];
  const torque = useAppStore((s) => !!s.control?.torque_enabled);
  const [lut, setLut] = useState<LutState | null>(null);
  // A global study map already maps every /joints/target: the table on top would map twice.
  const globalMap = useStudyMap((s) => (s.state?.enabled ? s.state.mode : null));
  const [mode, setMode] = useState<Mode>("lut");
  const [target, setTarget] = useState<Record<string, number>>({});
  const [last, setLast] = useState<LutCommand | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, Partial<Record<Mode, Result>>>>({});
  const [force, setForce] = useState<Record<string, number>>({});
  const sent = useRef<Record<string, number> | null>(null);
  const gen = useRef(0);
  const forces = useRef<Record<string, number>>({});
  const debounce = useRef<number | undefined>(undefined);
  const onTargetRef = useRef(onTarget);
  onTargetRef.current = onTarget;

  useStreamFrame((f) => {
    const F = f.tactile.forces;
    if (!F) return;
    for (const [k, v] of Object.entries(F)) {
      if (v) forces.current[k] = Math.hypot(v[0], v[1], v[2]);
    }
  });
  useEffect(() => {
    const id = window.setInterval(() => setForce({ ...forces.current }), 250);
    return () => window.clearInterval(id);
  }, []);
  useEffect(() => {
    visualApi.lut().then(setLut).catch((e: Error) => setError(e.message));
    void useStudyMap.getState().load();
  }, []);
  useEffect(() => {
    if (!lut?.available || globalMap) setMode("standard");
  }, [lut, globalMap]);
  useEffect(() => {
    onTargetRef.current(Object.keys(target).length ? target : null, lut?.mount ?? null);
  }, [target, lut]);
  useEffect(
    () => () => {
      gen.current++;
      onTargetRef.current(null, null);
      void post("/torque/disable").catch(() => undefined);
    },
    [],
  );

  const full = (q: Record<string, number>) =>
    Object.fromEntries(joints.map((j) => [j.id, q[j.id] ?? 0]));

  // Ramp the command from where it last was, at RAMP_DEG_S; a newer move cancels this one.
  async function moveTo(q: Record<string, number>, m: Mode) {
    const my = ++gen.current;
    const want = full(q);
    setTarget(want);
    const r = await visualApi.lutCommand(want, m === "lut");
    setLast(r);
    const start = sent.current ?? { ...full({}), ...latest.joints.estimate };
    const span = Math.max(...Object.keys(r.command).map((j) => Math.abs(r.command[j] - (start[j] ?? 0))), 0);
    const n = Math.max(1, Math.ceil((span / RAMP_DEG_S) * HZ));
    for (let k = 1; k <= n; k++) {
      if (gen.current !== my) return false;
      const f = k / n;
      const angles = Object.fromEntries(
        Object.keys(r.command).map((j) => [j, (start[j] ?? 0) + f * (r.command[j] - (start[j] ?? 0))]),
      );
      await post("/joints/target", { angles });
      sent.current = angles;
      await sleep(1000 / HZ);
    }
    return gen.current === my;
  }

  const run = (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    fn()
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(null));
  };

  const slide = (id: string, v: number) => {
    const next = { ...full(target), [id]: v };
    setTarget(next);
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => {
      if (torque) moveTo(next, mode).catch((e: Error) => setError(e.message));
    }, 120);
  };

  async function touchTest(finger: string, m: Mode) {
    const pose = lut?.touch[finger];
    if (!pose) throw new Error("no touch pose");
    if (!(await moveTo({}, m))) return;
    await sleep(1200);
    await post("/tactile/zero").catch(() => undefined);
    await sleep(500);
    if (!(await moveTo(pose, m))) return;
    await sleep(1500);
    let thumb = 0;
    let other = 0;
    for (let i = 0; i < 10; i++) {
      thumb = Math.max(thumb, forces.current.thumb ?? 0);
      other = Math.max(other, forces.current[finger] ?? 0);
      await sleep(100);
    }
    setResults((r) => ({ ...r, [finger]: { ...r[finger], [m]: { thumb, finger: other } } }));
    await moveTo({}, m);
  }

  const cell = (r: Result | undefined) => {
    if (!r) return <td>—</td>;
    const hit = Math.min(r.thumb, r.finger) >= TOUCH_N;
    return (
      <td className={hit ? "ok" : "warn"} title={`thumb ${r.thumb.toFixed(2)} N · finger ${r.finger.toFixed(2)} N`}>
        {hit ? "touch" : "no touch"} ({Math.min(r.thumb, r.finger).toFixed(2)} N)
      </td>
    );
  };

  return (
    <div className="visual-cal-hint visual-cal-sandbox">
      <div className="visual-cal-sandbox-row">
        <button className="btn" disabled={!!busy} onClick={() => run("torque", () => post(torque ? "/torque/disable" : "/torque/enable").then(() => (sent.current = null)))}>
          {torque ? "Torque off" : "Torque on"}
        </button>
        <label className="toggle-label" title={globalMap ? `global study map "${globalMap}" is on: commands are already mapped` : lut?.available ? "" : "no lookup table yet"}>
          <input type="checkbox" checked={mode === "lut"} disabled={!lut?.available || !!globalMap} onChange={(e) => setMode(e.target.checked ? "lut" : "standard")} />
          lookup table (accurate)
        </label>
        <button className="btn" disabled={!torque || !!busy} onClick={() => run("open", () => moveTo({}, mode))}>
          Open hand
        </button>
        {busy && <span>{busy}…</span>}
      </div>
      {lut?.summary && <span>{lut.summary}</span>}
      {error && <span className="warn">{error}</span>}

      <table className="visual-cal-joints">
        <thead>
          <tr><th>touch test</th><th>standard</th><th>lookup table</th><th /></tr>
        </thead>
        <tbody>
          {FINGERS.map((f) => (
            <tr key={f}>
              <td>thumb → {f}</td>
              {cell(results[f]?.standard)}
              {cell(results[f]?.lut)}
              <td>
                <button className="btn" disabled={!torque || !!busy || !lut?.touch[f]} onClick={() => run(`${f}, standard`, () => touchTest(f, "standard"))}>std</button>{" "}
                <button className="btn" disabled={!torque || !!busy || !lut?.available || !lut?.touch[f]} onClick={() => run(`${f}, lookup table`, () => touchTest(f, "lut"))}>LUT</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <span>
        tactile |F|: {["thumb", ...FINGERS].map((k) => `${k} ${(force[k] ?? 0).toFixed(2)}`).join(" · ")} N
      </span>

      <table className="visual-cal-joints">
        <thead>
          <tr><th>joint</th><th>want °</th><th /><th>sent °</th><th>reaches °</th></tr>
        </thead>
        <tbody>
          {joints.map((j) => {
            const v = target[j.id] ?? 0;
            const c = last?.command[j.id];
            const r = last?.reached?.[j.id];
            return (
              <tr key={j.id}>
                <td>{j.id}</td>
                <td>{v.toFixed(0)}</td>
                <td>
                  <input type="range" min={j.rom[0]} max={j.rom[1]} step={1} value={v} disabled={!torque || !!busy} onChange={(e) => slide(j.id, +e.target.value)} />
                </td>
                <td>{c == null ? "—" : c.toFixed(1)}</td>
                <td className={r != null && Math.abs(r - v) > 3 ? "warn" : ""}>{r == null ? "—" : r.toFixed(1)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <span>
        want: the true angle you ask for · sent: the command (the table's inverse, or the same angle on standard) ·
        reaches: where the table predicts the joint really ends up. The CAD hand on the camera image is drawn at “want”.
      </span>
    </div>
  );
}
