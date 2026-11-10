// The hand step's board choice: the console must take the hand's board, never
// the turntable's. The turntable's board answers ORCA_ID? as a hand too, so it
// is marked (by its pinned USB serial, from the rig) and cannot be picked here.

import { useEffect, useState } from "react";
import { api } from "../../api/rest";
import type { BoardEntry, BoardsInfo } from "../../api/types";
import { useAppStore } from "../../state/appStore";
import type { RigInfo } from "./api";

const short = (d: string) => d.split("/").pop() || d;
const ROW = {
  display: "flex",
  gap: 12,
  alignItems: "center",
  justifyContent: "space-between",
} as const;

export function HandBoard({ rig }: { rig: RigInfo | null }) {
  const [info, setInfo] = useState<BoardsInfo | null>(null);
  const [scanning, setScanning] = useState(false);
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null);
  const status = useAppStore((s) => s.status);
  const rigPorts = new Set(rig?.rig_board.devices ?? []);
  const isTurntable = (b: BoardEntry) =>
    b.ports.some((p) => rigPorts.has(p)) || rigPorts.has(b.device);

  const scan = async () => {
    setScanning(true);
    try {
      setInfo(await api.boards());
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    } finally {
      setScanning(false);
    }
  };
  useEffect(() => {
    void scan();
  }, []);

  const pick = async (b: BoardEntry) => {
    if (isTurntable(b)) {
      setNote({
        text: `${short(b.device)} is the turntable’s board: pick the hand’s.`,
        bad: true,
      });
      return;
    }
    try {
      setInfo(await api.selectBoard(b.device));
      setNote({
        text: `console pinned to ${short(b.device)}: connecting…`,
        bad: false,
      });
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    }
  };

  const pinned = status?.board_pinned ?? info?.selected ?? null;
  const pinnedIsRig = !!pinned && rigPorts.has(pinned);
  return (
    <div
      className="visual-cal-boards"
      style={{ display: "grid", gap: 8, margin: "8px 0" }}
    >
      <div style={ROW}>
        <span>
          hand: <b>{status?.state ?? "?"}</b>
          {pinned ? ` · pinned to ${short(pinned)}` : " · not pinned (auto)"}
        </span>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => void scan()}
          disabled={scanning}
        >
          {scanning ? "scanning…" : "Scan again"}
        </button>
      </div>
      {pinnedIsRig && (
        <p className="gt-warning">
          The console is pinned to the turntable’s board. Pick the hand’s board
          below.
        </p>
      )}
      {!pinned && (
        <p className="visual-cal-hint">
          Unpinned, the console takes the first board that answers, which can be
          the turntable’s. Pick the hand’s.
        </p>
      )}
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "grid",
          gap: 6,
        }}
      >
        {(info?.boards ?? []).map((b) => {
          const rigBoard = isTurntable(b);
          const what =
            [b.side, b.model_name && `(${b.model_name})`]
              .filter(Boolean)
              .join(" ") || b.kind;
          return (
            <li key={b.device} style={{ ...ROW, opacity: rigBoard ? 0.6 : 1 }}>
              <span>
                <b>{short(b.device)}</b> ·{" "}
                {rigBoard ? "turntable (rig board)" : what}
                {b.serial ? ` · S/N ${b.serial}` : ""}
                {b.held_by_console
                  ? " · this console"
                  : b.busy
                    ? " · in use"
                    : ""}
              </span>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => void pick(b)}
                disabled={rigBoard || pinned === b.device}
                title={
                  rigBoard
                    ? "The turntable’s board: never the hand’s"
                    : "Connect the console to this board"
                }
              >
                {pinned === b.device
                  ? "picked"
                  : rigBoard
                    ? "turntable"
                    : "This is the hand"}
              </button>
            </li>
          );
        })}
        {info && !info.boards.length && <li>no boards found</li>}
      </ul>
      {rig?.rig_board.usb_serial && (
        <p className="visual-cal-hint">
          Turntable board: USB serial …{rig.rig_board.usb_serial.slice(-12)}
          {rig.rig_board.devices.length
            ? ` (${rig.rig_board.devices.map(short).join(", ")})`
            : " (not plugged in)"}
          .
        </p>
      )}
      {note && (
        <p className={`visual-cal-note${note.bad ? " warn" : ""}`}>
          {note.text}
        </p>
      )}
    </div>
  );
}
