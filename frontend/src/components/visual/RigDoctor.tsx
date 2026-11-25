// "Check this computer": orca_core's rig doctor (visual_calibration/doctor.py, GET /doctor), what
// this computer has for the rig. It reads the system's listings only, never opening a camera or a
// port. Problems first, each two lines until clicked open, its fix to copy (once when several share
// it); the passing checks on request.

import { useCallback, useEffect, useState } from "react";
import { visualApi, type Doctor, type DoctorCheck } from "./api";

const ORDER = { error: 0, warn: 1, ok: 2 } as const;
let last: Doctor | null = null; // kept across step changes; "Check again" asks anew

function Fix({ text, open }: { text: string; open: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = () =>
    void navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      },
      () => undefined,
    );
  return (
    <div className="visual-cal-fix" onClick={(e) => e.stopPropagation()}>
      <code className={open ? "" : "clamp"}>{text}</code>
      <button
        className="btn btn-secondary btn-sm"
        onClick={copy}
        title="Copy the fix"
      >
        {copied ? "copied" : "copy"}
      </button>
    </div>
  );
}

function Row({ check, sameFix }: { check: DoctorCheck; sameFix: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <li className={check.status} onClick={() => setOpen(!open)} title={open ? "" : "Click for all of it"}>
      <span className={`visual-cal-dot ${check.status}`} />
      <span className={open ? "" : "clamp"}>
        <b>{check.name.replace(/_/g, " ")}</b>
        {check.detail ? ` · ${check.detail}` : ""}
      </span>
      {check.fix &&
        check.status !== "ok" &&
        (sameFix ? <span className="visual-cal-fix dim">the same fix as above</span> : <Fix text={check.fix} open={open} />)}
    </li>
  );
}

export function RigDoctor() {
  const [result, setResult] = useState<Doctor | null>(last);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [all, setAll] = useState(false);
  const check = useCallback(() => {
    setRunning(true);
    setError(null);
    visualApi
      .doctor()
      .then((d) => {
        last = d;
        setResult(d);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setRunning(false));
  }, []);
  useEffect(() => {
    if (!last) check();
  }, [check]);

  const checks = [...(result?.checks ?? [])].sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  const errors = checks.filter((c) => c.status === "error").length;
  const warns = checks.filter((c) => c.status === "warn").length;
  const shown = all ? checks : checks.filter((c) => c.status !== "ok");
  const summary = running
    ? "checking…"
    : error
      ? error
      : !result
        ? ""
        : errors || warns
          ? [errors && `${errors} problem${errors > 1 ? "s" : ""}`, warns && `${warns} warning${warns > 1 ? "s" : ""}`]
              .filter(Boolean)
              .join(", ")
          : `all ${checks.length} checks pass`;
  return (
    <div className={`visual-cal-doctor${errors ? " error" : warns ? " warn" : ""}`}>
      <div className="visual-cal-doctor-head">
        <span>
          <b>Check this computer</b>
          <span className={errors ? "err" : warns ? "warn" : "dim"}> · {summary}</span>
        </span>
        <button className="btn btn-secondary btn-sm" onClick={check} disabled={running}>
          Check again
        </button>
      </div>
      {shown.length > 0 && (
        <ul>
          {shown.map((c, i) => (
            <Row key={c.name} check={c} sameFix={!!c.fix && shown.slice(0, i).some((p) => p.fix === c.fix)} />
          ))}
        </ul>
      )}
      {checks.some((c) => c.status === "ok") && (
        <button className="visual-cal-link" onClick={() => setAll(!all)}>
          {all ? "hide the passing checks" : `show all ${checks.length} checks`}
        </button>
      )}
    </div>
  );
}
