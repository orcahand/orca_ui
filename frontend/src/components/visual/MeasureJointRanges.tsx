// The assemblers' hand steps after the rig is calibrated (orca_core hand_study.run_hand):
// calibrate the motor stops (Setup's own Calibrate step), measure the joint ranges on the
// rig (a run of about an hour that the console's backend owns), the results per joint with
// the hand's accuracy before and after, and writing them to the hand's board.

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/rest";
import { useAppStore } from "../../state/appStore";
import { isOperationActive, useOperationStore } from "../../state/operationStore";
import { HandDetails } from "../hand/HandDetails";
import { CalibrateStep } from "../setup/CalibrateStep";
import { shortDate } from "../setup/setupUtils";
import {
  handRunPhotoUrl,
  visualApi,
  type BoardWriter,
  type ErrorStats,
  type HandRun,
  type HandRunResults,
} from "./api";

const POLL_MS = 2000;

/** Whether the connected hand's calibration in force was taken today. */
export function calibratedToday(at: string | null | undefined): boolean {
  return !!at && new Date(at).toDateString() === new Date().toDateString();
}

/** The hand run, polled while `on` (every 2 s while it runs, else every 10 s). */
export function useHandRun(on: boolean): [HandRun | null, () => void] {
  const [run, setRun] = useState<HandRun | null>(null);
  const refresh = useCallback(() => {
    visualApi.handRun().then(setRun, () => undefined);
  }, []);
  const running = run?.state === "running";
  useEffect(() => {
    if (!on) return;
    refresh();
    const id = window.setInterval(refresh, running ? POLL_MS : 5 * POLL_MS);
    return () => window.clearInterval(id);
  }, [on, running, refresh]);
  return [run, refresh];
}

const minutes = (s: number | null | undefined) =>
  s === null || s === undefined ? "" : s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`;

export function runNote(run: HandRun | null): string {
  if (!run || run.state === "idle") return "~65 min";
  if (run.state === "running") {
    const block = run.progress?.steps.find((s) => s.state === "running");
    return block?.poses ? `${block.taken} / ${block.poses} · ${block.label}` : (block?.label ?? "starting");
  }
  return run.state === "ended" ? "listed (dry run)" : run.state;
}

export function HandCalibrate() {
  const handInfo = useAppStore((s) => s.handInfo);
  const at = handInfo?.hand?.calibration.calibrated_at ?? null;
  const today = calibratedToday(at);
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <p className={`visual-cal-note${today ? "" : " warn"}`}>
        {today
          ? `Calibrated today (${shortDate(at)}): go on to mount the hand.`
          : at
            ? `Last calibrated ${shortDate(at)}, not today: calibrate now.`
            : "No calibration on this computer yet: calibrate now."}
      </p>
      <CalibrateStep state={today ? "done" : "next"} />
    </div>
  );
}

export function MeasureRun({ run, refresh }: { run: HandRun | null; refresh: () => void }) {
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const handInfo = useAppStore((s) => s.handInfo);
  const handState = useAppStore((s) => s.status?.state ?? null);
  const operation = useOperationStore((s) => s.operation);
  const running = run?.state === "running";
  const p = run?.progress ?? null;
  const blocks = p?.steps.filter((s) => s.poses) ?? [];
  const total = blocks.reduce((n, s) => n + (s.poses ?? 0), 0);
  const taken = blocks.reduce((n, s) => n + (s.taken ?? 0), 0);
  const blocked =
    handState !== "connected"
      ? "connect the hand first"
      : isOperationActive(operation)
        ? "an operation is running"
        : null;

  const act = async (what: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setNote(null);
    try {
      await what();
      setNote({ text: done, bad: false });
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    } finally {
      setBusy(false);
      refresh();
    }
  };
  const start = () =>
    act(async () => {
      await visualApi.connect(false); // the plate read-only (torque off), if the watcher has not
      await visualApi.handRunStart();
    }, "cameras checked: measuring");
  const stop = () => act(() => visualApi.handRunStop(), "stopped: hand and plate torque off");

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div className="flow-row" style={{ gap: 8, alignItems: "center" }}>
        <span>
          hand <code>{run?.hand ?? handInfo?.hand?.id ?? "?"}</code>
        </span>
        {running ? (
          <button className="btn btn-secondary" onClick={() => void stop()} disabled={busy}>
            Stop
          </button>
        ) : (
          <button
            className="btn btn-primary"
            onClick={() => void start()}
            disabled={busy || !!blocked}
            title={blocked ?? "Check both cameras, then start the run (about 65 minutes)"}
          >
            {busy ? "checking the cameras…" : run && run.state !== "idle" ? "Measure again" : "Measure"}
          </button>
        )}
        {blocked && !running && <span className="visual-cal-hint">{blocked}</span>}
      </div>
      {note && <p className={`visual-cal-note${note.bad ? " warn" : ""}`}>{note.text}</p>}
      {run && run.state !== "idle" && (
        <>
          <p className={`visual-cal-note${["failed", "stopped"].includes(run.state) ? " warn" : ""}`}>
            {run.state === "running"
              ? `measuring · ${taken} / ${total} poses${p?.eta_s ? ` · about ${minutes(p.eta_s)} left` : ""}`
              : run.state === "done"
                ? "done: the ranges are recorded on this computer (see Results)"
                : run.state === "stopped"
                  ? `stopped (${run.stopped}): hand and plate torque off`
                  : run.state === "ended"
                    ? "dry run: the steps below were planned, nothing moved"
                    : `failed${p?.error ? `: ${p.error}` : ""}`}
          </p>
          {total > 0 && (
            <div className="setup-progress" title={`${taken} of ${total} poses`}>
              <div className="setup-progress-fill" style={{ width: `${(taken / total) * 100}%` }} />
            </div>
          )}
          <ol className="setup-copy visual-cal-items">
            {(p?.steps ?? []).map((s) => (
              <li key={s.name} style={{ opacity: s.state === "todo" ? 0.6 : 1 }}>
                {s.state === "done" ? "✓ " : s.state === "running" ? "● " : ""}
                {s.label}
                {s.poses ? ` · ${s.taken} / ${s.poses} poses` : ""}
              </li>
            ))}
          </ol>
          {Object.keys(p?.photos ?? {}).length > 0 && (
            <div style={{ display: "flex", gap: 8 }}>
              {Object.entries(p!.photos).map(([cam, path]) => (
                <figure key={cam} style={{ margin: 0, flex: 1 }}>
                  <img
                    src={handRunPhotoUrl(cam, path)}
                    alt={`camera ${cam}`}
                    style={{ width: "100%", display: "block" }}
                  />
                  <figcaption className="visual-cal-hint">
                    camera {cam.toUpperCase()} · {path.split("/").slice(-2).join("/")}
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
          {run.state !== "running" && run.state !== "done" && !!run.log_tail?.length && (
            <details>
              <summary className="visual-cal-hint">log ({run.log})</summary>
              <pre className="visual-cal-hint" style={{ whiteSpace: "pre-wrap" }}>
                {run.log_tail.join("\n")}
              </pre>
            </details>
          )}
        </>
      )}
    </div>
  );
}

const range = (r: [number, number]) => `${r[0].toFixed(1)} … ${r[1].toFixed(1)}`;
const err = (e: ErrorStats | null | undefined) => (e ? `${e.rms.toFixed(1)} / ${e.max.toFixed(1)}` : "–");

export function MeasureResults({ run }: { run: HandRun | null }) {
  const [res, setRes] = useState<HandRunResults | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const handInfo = useAppStore((s) => s.handInfo);
  const ended = run?.ended ?? null;
  useEffect(() => {
    visualApi.handRunResults().then(
      (r) => {
        setRes(r.results);
        setNote(r.results ? null : `no measured run of ${r.hand} on this rig yet`);
      },
      (e: Error) => setNote(e.message),
    );
  }, [ended]);
  if (!res) return <p className="visual-cal-note">{note ?? "loading…"}</p>;
  const acc = res.accuracy;
  const measured = Object.values(res.joints).filter((j) => j.measured).length;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <p className="visual-cal-note">
        Run of {res.started ? shortDate(res.started) : "?"} on rig {res.rig}: {measured} of{" "}
        {Object.keys(res.joints).length} joints measured from {res.poses} poses.{" "}
        {res.joint_ranges ? `Recorded in ${res.joint_ranges}.` : "No joint measured: nothing recorded."}
      </p>
      {/* TODO(quality gate): which joints get a measured range is not decided; for now every joint
          the fit's coverage check passes (the motor covered min_span of its range). */}
      <p className="visual-cal-hint">
        Measured: the motor covered at least {Math.round((res.min_span ?? 0) * 100)}% of the joint’s range in the
        short block (the fit’s coverage check). Not measured: the range in force stays. No quality gate yet.
      </p>
      <table className="visual-cal-joints">
        <thead>
          <tr>
            <th>joint</th>
            <th>before (°)</th>
            <th>measured (°)</th>
            <th title="RMS / max error on the 25-pose check, before and after (deg)">check before → after</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(res.joints).map(([j, s]) => (
            <tr key={j} style={{ opacity: s.measured ? 1 : 0.6 }}>
              <td>{j}</td>
              <td>{range(s.old)}</td>
              <td title={s.measured ? `${s.n} poses, fit rms ${s.rms}°` : "not measured: coverage too small"}>
                {s.measured ? range(s.new) : "not measured"}
              </td>
              <td>
                {acc ? `${err(acc.before[j])} → ${err(acc.after[j])}` : "–"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="visual-cal-note">
        {acc
          ? `Accuracy on the check (${acc.n} of ${acc.n_all} poses solved well), RMS / max: ${err(acc.before.all)}° before → ${err(acc.after.all)}° after.`
          : "No accuracy yet: the check’s photos were not solved."}
      </p>
      {handInfo?.hand && <HandDetails hand={handInfo.hand} />}
    </div>
  );
}

export function BoardWrite() {
  const [writer, setWriter] = useState<BoardWriter | null>(null);
  const [error, setError] = useState<string | null>(null);
  const operation = useOperationStore((s) => s.operation);
  const handInfo = useAppStore((s) => s.handInfo);
  useEffect(() => {
    visualApi.boardWriter().then(setWriter, (e: Error) => setError(e.message));
  }, []);
  const mine = operation?.kind === "board_write" ? operation : null;
  const active = isOperationActive(mine);
  const result = mine?.state === "done" ? (mine.result as BoardWriteResult | null) : null;
  if (!writer) return <p className="visual-cal-note">{error ?? "loading…"}</p>;
  if (!writer.available)
    return (
      <p className="visual-cal-note">
        Not offered on this computer: {writer.reason}. The measured ranges stay in force here (the hand’s
        joint_ranges.yaml).
      </p>
    );
  const write = () => {
    setError(null);
    api.operationStart("board_write").catch((e: Error) => setError(e.message));
  };
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div className="flow-row" style={{ gap: 8, alignItems: "center" }}>
        <button
          className="btn btn-primary"
          onClick={write}
          disabled={active || isOperationActive(operation)}
          title={`The hand lets go of its port, the board is written with ${writer.tool}, read back, and the hand reconnects`}
        >
          {active ? "writing…" : "Write to board"}
        </button>
        {active && <span className="visual-cal-hint">{mine?.detail ?? mine?.phase}</span>}
      </div>
      {error && <p className="visual-cal-note warn">{error}</p>}
      {mine?.state === "error" && <p className="visual-cal-note warn">{mine.error}</p>}
      {result && (
        <p className={`visual-cal-note${result.written && result.confirmed ? "" : " warn"}`}>
          {!result.written
            ? `Not written: ${result.reason}`
            : result.confirmed && result.board
              ? `Written and read back: the board holds calibration ${result.board.sequence} and the ranges of ${result.board.ranges.length} joints.`
              : `Written, but the read-back differs: board sequence ${result.board?.sequence ?? "?"} (wrote ${result.sequence}), ranges of ${result.board?.ranges.length ?? 0} joints (file: ${result.file_ranges.length}).`}
        </p>
      )}
      {handInfo?.hand && <HandDetails hand={handInfo.hand} />}
    </div>
  );
}

interface BoardWriteResult {
  written: boolean;
  reason: string | null;
  sequence: number | null;
  file_ranges: string[];
  confirmed: boolean;
  board: { sequence: number; serial: string | null; ranges: string[]; ranges_measured_at: string | null } | null;
}
