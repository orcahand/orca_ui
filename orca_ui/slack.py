"""Slack notifications for endurance tests, over an Incoming Webhook.

One webhook URL is one channel. Everything the endurance recorder wants the
channel to know arrives here and leaves on a single background thread, so
nothing that feeds the recorder (the operation thread holding at a waypoint,
the telemetry ticks) ever touches the network or waits on it.

Two kinds of message:

- **Immediate**: test started / stopped, operator notes, calibration
  checkpoints, the periodic heartbeat and on-demand digests. One post each.
- **Coalesced**: timeline events. The first event after a quiet spell posts
  at once so a fault shows up straight away; anything that follows within
  ``EVENT_WINDOW_S`` is folded into one post at the end of the window, so a
  flapping sensor that transitions every tick costs one message a minute.

Bounded everywhere: the outbound queue, the coalescing buffer, the retry
budget and the log volume. When Slack is unreachable, messages are dropped
after their retries and the next successful post says how many. Nothing here
raises to a caller.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

EVENT_WINDOW_S = 60.0
MAX_EVENT_LINES = 15
MAX_PENDING_EVENTS = 200
QUEUE_SIZE = 64
POST_TIMEOUT_S = 10.0
RETRY_DELAYS_S = (2.0, 8.0, 30.0)
# Slack caps a section's text at 3000 characters; stay well under.
MAX_BLOCK_CHARS = 2800

SEVERITY_ICON = {"bad": "🔴", "ok": "🟢"}
KIND_ICON = {"operation": "▶️", "torque": "⚡", "fault": "🔴", "tactile": "🖐️",
             "encoder": "📐", "link": "🔌"}


def fmt_hours(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    hours = float(seconds) / 3600.0
    if hours < 1.0:
        return f"{float(seconds) / 60.0:.0f} min"
    return f"{hours:.1f} h" if hours < 100 else f"{hours:.0f} h"


def fmt_delta(value: float | None, digits: int = 1, unit: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}{unit}"


def _clip(text: str, limit: int = MAX_BLOCK_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _event_line(event: dict) -> str:
    severity = event.get("severity")
    icon = (SEVERITY_ICON[severity] if severity in ("bad", "ok")
            else KIND_ICON.get(event.get("kind"), "▫️"))
    cycle = event.get("cycle")
    where = fmt_hours(event.get("t"))
    if cycle:
        where += f" · cycle {int(cycle):,}"
    return f"{icon} {where} · *{event.get('subject')}*: {event.get('detail')}"


class SlackNotifier:
    """Fire-and-forget poster. ``hand`` names the hand in every message,
    ``console_url`` links back to the UI, ``digest`` returns the active
    test's digest for the heartbeat (None when nothing is running)."""

    def __init__(self, webhook_url: str, *, hand: Callable[[], str | None],
                 console_url: str | None = None, mention: str | None = None,
                 heartbeat_s: float = 3600.0,
                 digest: Callable[[], dict | None] | None = None):
        self._url = webhook_url
        self._hand = hand
        self._console_url = console_url
        self._mention = (mention or "").strip() or None
        self._heartbeat_s = max(float(heartbeat_s or 0.0), 0.0)
        self._digest = digest
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="slack-notify",
                                        daemon=True)
        self._lock = threading.Lock()
        self._dropped = 0
        self._started = False

    # ----- lifecycle ----------------------------------------------------------

    def bind_digest(self, digest: Callable[[], dict | None]) -> None:
        """Late-bound heartbeat source (the recorder exists after the
        notifier does)."""
        self._digest = digest

    def start(self) -> None:
        if not self._started:
            self._started = True
            self._thread.start()

    def close(self, timeout_s: float = 3.0) -> None:
        """Stop the worker, giving it a moment to drain what is queued."""
        self._stop.set()
        if self._started:
            self._thread.join(timeout=timeout_s)

    # ----- producers (any thread, never block, never raise) -------------------

    def test_started(self, digest: dict) -> None:
        self._enqueue(("post", self._compose(
            f"▶️ Endurance test *{digest.get('label')}* started",
            self._test_context(digest),
            body=self._test_link(digest))))

    def test_stopped(self, digest: dict) -> None:
        self._enqueue(("post", self._compose(
            f"🏁 Endurance test *{digest.get('label')}* stopped",
            self._test_context(digest),
            body=self._digest_body(digest))))

    def note(self, digest: dict, text: str) -> None:
        self._enqueue(("post", self._compose(
            f"📝 Note on *{digest.get('label')}*",
            self._test_context(digest),
            body=_clip(text))))

    def checkpoint(self, digest: dict, checkpoint: dict, deltas: dict) -> None:
        """A calibration run finished during the test: motor travel per
        joint, with the change since the test's first checkpoint."""
        lines = []
        for joint, travel in sorted((checkpoint.get("travel_deg") or {}).items()):
            lines.append(f"`{joint:<14}` {travel:7.1f}°  "
                         f"({fmt_delta(deltas.get(joint), 1, '°')})")
        problems = checkpoint.get("problems") or []
        body = "*Motor travel between hardstops* (Δ since first checkpoint)\n"
        body += "\n".join(lines) if lines else "_no travel recorded_"
        if problems:
            body += "\n⚠️ " + "\n⚠️ ".join(problems)
        if not checkpoint.get("completed"):
            body += "\n⚠️ calibration did not complete"
        alert = bool(problems) or not checkpoint.get("completed")
        self._enqueue(("post", self._compose(
            f"📐 Calibration checkpoint on *{digest.get('label')}*",
            self._test_context(digest), body=body, alert=alert)))

    def event(self, digest: dict, event: dict) -> None:
        self._enqueue(("event", digest, event))

    def digest(self, digest: dict, *, title: str | None = None) -> None:
        """On-demand or heartbeat digest of one test."""
        state = "running" if digest.get("active") else "stopped"
        self._enqueue(("post", self._compose(
            title or f"📊 *{digest.get('label')}* — {state}",
            self._test_context(digest), body=self._digest_body(digest))))

    def console_started(self, digest: dict | None) -> None:
        text = "🟢 ORCA console up, Slack notifications on"
        if digest is not None:
            text += f" — resuming endurance test *{digest.get('label')}*"
        self._enqueue(("post", self._compose(text, self._context([]))))

    def _enqueue(self, item: tuple) -> None:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            with self._lock:
                self._dropped += 1

    # ----- composition --------------------------------------------------------

    def _context(self, parts: list[str]) -> str:
        hand = None
        try:
            hand = self._hand()
        except Exception:
            pass
        items = [hand] if hand else []
        items += [p for p in parts if p]
        if self._console_url:
            items.append(f"<{self._console_url}|console>")
        return " · ".join(items)

    def _test_context(self, digest: dict) -> str:
        parts = [f"{fmt_hours(digest.get('elapsed_s'))} elapsed",
                 f"{int(digest.get('cycles_total') or 0):,} cycles",
                 f"{int(digest.get('samples') or 0):,} holds"]
        return self._context(parts)

    def _test_link(self, digest: dict) -> str | None:
        if not self._console_url or not digest.get("id"):
            return None
        return (f"<{self._console_url}/api/endurance/tests/"
                f"{digest['id']}/samples.csv|raw samples (CSV)>")

    def _digest_body(self, digest: dict) -> str:
        lines: list[str] = []
        bad = int(digest.get("events_bad") or 0)
        events = int(digest.get("events") or 0)
        lines.append(f"*Events* {events} ({bad} bad) · "
                     f"*Runs* {int(digest.get('runs') or 0)} · "
                     f"*Checkpoints* {int(digest.get('checkpoints') or 0)}")
        open_bad = digest.get("open_bad") or []
        if open_bad:
            lines.append("*Still bad:* " + ", ".join(
                f"{e.get('subject')} ({e.get('detail')})" for e in open_bad[:8]))
        currents = digest.get("current_drift") or {}
        if currents:
            cells = []
            for motor, cell in currents.items():
                joint = cell.get("joint") or f"m{motor}"
                cells.append(f"`{joint}` {cell.get('now', 0):.0f} mA "
                             f"({fmt_delta(cell.get('pct'), 0, '%')})")
            lines.append("*Holding current at the hold, Δ vs. first hour:* "
                         + " · ".join(cells))
        forces = digest.get("forces") or {}
        if forces:
            lines.append("*Fingertip force at the hold:* " + ", ".join(
                f"{finger} {value:.2f} N" for finger, value in forces.items()))
        travel = digest.get("travel_drift") or {}
        if travel:
            lines.append("*Motor travel, Δ since first checkpoint:* " + ", ".join(
                f"`{joint}` {fmt_delta(delta, 1, '°')}"
                for joint, delta in travel.items()))
        link = self._test_link(digest)
        if link:
            lines.append(link)
        return "\n".join(lines)

    def _compose(self, title: str, context: str, *, body: str | None = None,
                 alert: bool = False) -> dict:
        blocks: list[dict] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": _clip(title)}},
        ]
        if body:
            blocks.append({"type": "section",
                           "text": {"type": "mrkdwn", "text": _clip(body)}})
        if context:
            blocks.append({"type": "context",
                           "elements": [{"type": "mrkdwn",
                                         "text": _clip(context, 1500)}]})
        text = title if not (alert and self._mention) else f"{self._mention} {title}"
        if alert and self._mention:
            blocks.insert(0, {"type": "section",
                              "text": {"type": "mrkdwn", "text": self._mention}})
        return {"text": text, "blocks": blocks}

    def _compose_events(self, digest: dict, events: list[dict],
                        overflow: int) -> dict:
        bad = any(e.get("severity") == "bad" for e in events)
        lines = [_event_line(e) for e in events[:MAX_EVENT_LINES]]
        hidden = overflow + max(len(events) - MAX_EVENT_LINES, 0)
        if hidden:
            lines.append(f"… and {hidden} more")
        noun = "event" if len(events) + overflow == 1 else "events"
        return self._compose(
            f"{'🔴' if bad else '▫️'} {len(events) + overflow} {noun} on "
            f"*{digest.get('label')}*",
            self._test_context(digest), body="\n".join(lines), alert=bad)

    # ----- worker -------------------------------------------------------------

    def _run(self) -> None:
        import httpx

        # httpx logs every request at INFO; one line per post is noise next
        # to the hardware diagnostics on the console.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        client = httpx.Client(timeout=POST_TIMEOUT_S,
                              limits=httpx.Limits(max_keepalive_connections=1))
        pending: list[dict] = []
        pending_digest: dict | None = None
        overflow = 0
        window_ends = 0.0
        last_event_post = float("-inf")
        next_heartbeat = (time.monotonic() + self._heartbeat_s
                          if self._heartbeat_s else float("inf"))
        failing = False
        try:
            while not self._stop.is_set() or not self._queue.empty():
                now = time.monotonic()
                deadline = min(window_ends if pending else float("inf"),
                               next_heartbeat)
                timeout = 0.0 if self._stop.is_set() else max(
                    0.05, min(deadline - now, 60.0))
                try:
                    item = self._queue.get(timeout=timeout)
                except queue.Empty:
                    item = None
                now = time.monotonic()

                if item is not None and item[0] == "event":
                    pending_digest, event = item[1], item[2]
                    if not pending and now - last_event_post >= EVENT_WINDOW_S:
                        # Quiet spell: the first event goes out straight away.
                        payload = self._compose_events(pending_digest, [event], 0)
                        failing = self._deliver(client, payload, failing)
                        last_event_post = now
                    elif len(pending) >= MAX_PENDING_EVENTS:
                        overflow += 1
                    else:
                        if not pending:
                            window_ends = max(last_event_post + EVENT_WINDOW_S,
                                              now)
                        pending.append(event)
                elif item is not None and item[0] == "post":
                    failing = self._deliver(client, item[1], failing)

                if pending and (now >= window_ends or self._stop.is_set()):
                    payload = self._compose_events(pending_digest or {}, pending,
                                                   overflow)
                    failing = self._deliver(client, payload, failing)
                    last_event_post = now
                    pending, overflow = [], 0

                if now >= next_heartbeat and not self._stop.is_set():
                    next_heartbeat = now + self._heartbeat_s
                    digest = None
                    try:
                        digest = self._digest() if self._digest else None
                    except Exception:
                        logger.debug("slack: heartbeat digest failed", exc_info=True)
                    if digest is not None:
                        failing = self._deliver(client, self._compose(
                            f"⏱️ *{digest.get('label')}* — "
                            f"{fmt_hours(digest.get('elapsed_s'))} in",
                            self._test_context(digest),
                            body=self._digest_body(digest)), failing)
        finally:
            client.close()

    def _deliver(self, client, payload: dict, failing: bool) -> bool:
        """Post once with a short retry budget. Returns the new failing
        state; logs on the first failure of a streak and on recovery."""
        with self._lock:
            dropped, self._dropped = self._dropped, 0
        if dropped:
            payload = dict(payload)
            payload["blocks"] = list(payload.get("blocks") or []) + [{
                "type": "context",
                "elements": [{"type": "mrkdwn",
                              "text": f"⚠️ {dropped} earlier message(s) were "
                                      f"dropped (Slack unreachable or queue full)"}],
            }]
        error = None
        for attempt, delay in enumerate((0.0,) + RETRY_DELAYS_S):
            if delay and self._stop.wait(delay):
                break
            try:
                response = client.post(self._url, json=payload)
            except Exception as e:  # transport errors, DNS, timeouts
                error = f"{type(e).__name__}: {e}"
                continue
            if response.status_code < 300:
                if failing:
                    logger.info("slack: delivery restored")
                return False
            error = f"HTTP {response.status_code}: {response.text[:120]}"
            if response.status_code == 429:
                try:
                    hold = float(response.headers.get("Retry-After") or 1.0)
                except ValueError:
                    hold = 1.0
                self._stop.wait(min(hold, 60.0))
            elif 400 <= response.status_code < 500:
                # Rejected payload or a revoked webhook: retrying cannot help.
                break
        with self._lock:
            self._dropped += 1
        if not failing:
            logger.warning("slack: could not post (%s) — further failures are "
                           "silent until delivery recovers", error)
        return True
