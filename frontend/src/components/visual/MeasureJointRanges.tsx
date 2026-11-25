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
const SWAPPED = /swapped/i; // the camera check found camera A where B should be, or the other way round

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

/** The console's run as this hand sees it: `mine` (this hand's run, or idle), `other` (another
 * hand's run, still measuring on the rig). A run of another hand that ended is not shown. */
export function runsFor(run: HandRun | null, handId: string | null): { mine: HandRun | null; other: HandRun | null } {
  if (!run || run.state === "idle" || !handId || run.hand === handId) return { mine: run, other: null };
  return { mine: null, other: run.state === "running" ? run : null };
}

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

export function MeasureRun({
  run,
  other,
  refresh,
}: {
  run: HandRun | null;
  other: HandRun | null;
  refresh: () => void;
}) {
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const handInfo = useAppStore((s) => s.handInfo);
  const handState = useAppStore((s) => s.status?.state ?? null);
  const operation = useOperationStore((s) => s.operation);
  const running = run?.state === "running" || !!other;
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
      {note?.bad && SWAPPED.test(note.text) && (
        <p className="visual-cal-note warn">
          Cameras A and B swapped: trade them in the rig config with{" "}
          <code>python -m visual_calibration.sweep --assign-cameras --swap</code> (in orca_core’s
          experiments/visual_calibration), then Measure again.
        </p>
      )}
      {other && (
        <p className="visual-cal-note warn">
          The rig is measuring hand {other.hand}: stop that run before measuring this hand.
        </p>
      )}
      {!!run?.dead_workers?.length && (
        <p className="visual-cal-note warn">
          A solve worker died: the poses are not being solved. See {run.dead_workers.join(", ")}.
        </p>
      )}
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
                    : `failed: ${run.reason ?? "see the log"}`}
            {partly(run) && " The joint ranges were recorded before that (see Results)."}
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

const runName = (path: string | null | undefined) => (path ?? "").split("/").pop() || "?";

/** A run that failed or was stopped after its fit had recorded the ranges (the accuracy check left). */
const partly = (run: HandRun | null) =>
  !!run && ["failed", "stopped"].includes(run.state) && !!run.progress?.recorded;
const why = (run: HandRun) => (run.state === "stopped" ? `it was stopped (${run.stopped})` : run.reason);

/** The connected hand's results: of this run once it is done; nothing from a run that failed or
 * was stopped; with no run here, the hand's newest measured run, named as an earlier one. */
export function MeasureResults({ run }: { run: HandRun | null }) {
  const [got, setGot] = useState<{ hand: string; latest: string | null; results: HandRunResults | null } | null>(
    null,
  );
  const [note, setNote] = useState<string | null>(null);
  const handInfo = useAppStore((s) => s.handInfo);
  const connected = useAppStore((s) => s.status?.state === "connected");
  const handId = handInfo?.hand?.id ?? null;
  const ended = run?.ended ?? null;
  useEffect(() => {
    setGot(null);
    if (!connected) return; // and again once the hand is back after a run (its new ranges in force)
    visualApi.handRunResults().then(
      (r) => {
        setGot(r);
        setNote(r.results ? null : `no measured run of ${r.hand} on this rig yet`);
      },
      (e: Error) => setNote(e.message),
    );
  }, [ended, connected, handId]);
  if (run?.state === "running")
    return <p className="visual-cal-note">Measuring: the results come when this run is done.</p>;
  if (run && ["failed", "stopped"].includes(run.state) && !partly(run))
    return (
      <p className="visual-cal-note warn">
        This run ({runName(run.run)}) {run.state === "stopped" ? `was stopped (${run.stopped})` : `failed: ${run.reason}`}:
        no results from it. Measure again.
      </p>
    );
  const res = got && got.hand === handId ? got.results : null; // another hand's never shows
  if (!res) return <p className="visual-cal-note">{note ?? "loading…"}</p>;
  if (partly(run) && res.run !== run!.run)
    return <p className="visual-cal-note">loading this run’s results…</p>;
  const thisRun = (run?.state === "done" || partly(run)) && run!.run === res.run;
  const acc = res.accuracy;
  const measured = Object.values(res.joints).filter((j) => j.measured).length;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {partly(run) && (
        <p className="visual-cal-note warn">
          Ranges recorded on this computer (in force once the hand reconnects); the accuracy check didn’t
          finish: {why(run!)}.{" "}
          <button className="btn btn-secondary btn-sm" onClick={() => void api.reconnect().catch(() => undefined)}>
            Reconnect the hand
          </button>
        </p>
      )}
      <p className={`visual-cal-note${thisRun ? "" : " warn"}`}>
        {thisRun ? "This run" : "An earlier run"}, {runName(res.run)} ({res.started ? shortDate(res.started) : "?"}, rig{" "}
        {res.rig}): {measured} of {Object.keys(res.joints).length} joints measured from {res.poses} poses.{" "}
        {res.joint_ranges ? `Recorded in ${res.joint_ranges}.` : "No joint measured: nothing recorded."}
        {!thisRun && got?.latest && got.latest !== res.run
          ? ` The hand’s newest run, ${runName(got.latest)}, recorded no ranges.`
          : ""}
      </p>
      {res.joint_ranges && (
        <p className="visual-cal-hint">
          The hand’s joint_ranges.yaml was replaced whole: a joint not measured in this run has no measured range
          on this computer, it uses the model’s range here. For a hand whose ranges came from its board, those
          joints fall back to the model’s range here too, and the next Write to board would drop them from the
          board.
          {res.gone.length
            ? ` Had a measured range before this run, now the model’s: ${res.gone.join(", ")}.`
            : ""}
        </p>
      )}
      {/* TODO(quality gate): which joints get a measured range is not decided; for now every joint
          the fit's coverage check passes (the motor covered min_span of its range). */}
      <p className="visual-cal-hint">
        Measured: the motor covered at least {Math.round((res.min_span ?? 0) * 100)}% of the joint’s range in the
        short block (the fit’s coverage check), and its fit is a range. No quality gate yet.
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
              <td
                title={
                  s.measured
                    ? `${s.n} poses, fit rms ${s.rms}°`
                    : (s.rejected ?? (s.uncalibrated ? "no calibration for this joint" : "coverage too small"))
                }
              >
                {s.measured ? range(s.new) : s.rejected ? "left out" : "not measured"}
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
  const handId = handInfo?.hand?.id ?? null;
  const mine = operation?.kind === "board_write" ? operation : null;
  const active = isOperationActive(mine);
  const done = mine?.state === "done" ? (mine.result as BoardWriteResult | null) : null;
  const result = done && done.hand === handId ? done : null; // another hand's write is not this hand's
  if (!writer) return <p className="visual-cal-note">{error ?? "loading…"}</p>;
  if (!writer.available)
    return (
      <div className="visual-cal-explain">
        <p>
          Not offered on this computer: <WithPath text={writer.reason ?? ""} path={writer.looked_in} />.
        </p>
        <p>The measured ranges stay in force here (the hand’s joint_ranges.yaml).</p>
      </div>
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
          {active ? "writing…" : `Write hand ${handId ?? "?"} to its board`}
        </button>
        {active && <span className="visual-cal-hint">{mine?.detail ?? mine?.phase}</span>}
      </div>
      {error && <p className="visual-cal-note warn">{error}</p>}
      {mine?.state === "error" && <p className="visual-cal-note warn">{mine.error}</p>}
      {result && (
        <p className={`visual-cal-note${result.written && result.confirmed ? "" : " warn"}`}>
          {`Hand ${result.hand}: `}
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

/** `text` with `path` (where it occurs) on a line of its own. */
function WithPath({ text, path }: { text: string; path?: string }) {
  const at = path ? text.indexOf(path) : -1;
  if (!path || at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at).trimEnd()}
      <code className="visual-cal-path">{path}</code>
      {text.slice(at + path.length).trimStart()}
    </>
  );
}

interface BoardWriteResult {
  hand: string;
  written: boolean;
  reason: string | null;
  sequence: number | null;
  file_ranges: string[];
  confirmed: boolean;
  board: { sequence: number; serial: string | null; ranges: string[]; ranges_measured_at: string | null } | null;
}
