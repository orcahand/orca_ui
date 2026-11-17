"""Stream topic names and per-topic browser-facing rate ceilings.

Producers already pace the mid/slow topics (samplers run at 10 Hz / 1 Hz),
so only the high-rate topics carry a broadcast throttle. ``0`` means
"forward every new publish".
"""

STATUS = "status"
CONTROL_STATE = "control.state"
ERROR = "error"

# Long-running operations (calibrate/tension/replay/...). operation.log is a
# CUMULATIVE payload ({run_id, next_seq, lines}) because the hub coalesces
# latest-wins — per-line publishes would drop burst lines.
OPERATION_STATE = "operation.state"
OPERATION_LOG = "operation.log"

TACTILE_FORCES = "tactile.forces"
TACTILE_TAXELS = "tactile.taxels"

JOINTS_MEASURED = "joints.measured"
JOINTS_ESTIMATE = "joints.estimate"
JOINTS_TARGET = "joints.target"
JOINTS_CORRECTION = "joints.correction"

MOTORS_TELEMETRY = "motors.telemetry"
# Per-motor fault table: bus-error counters (parsed from orca_core's motor
# client logs) and command adherence (target vs sampled pose, stall
# durations). 1 Hz from telemetry's slow tick; counters reset per session.
MOTORS_FAULTS = "motors.faults"
STATS = "stats"

# Electrical bring-up monitor: per-joint encoder health verdicts, tactile
# connection state, and sensing-link counters (browser twin of orca_core's
# scripts/monitor_sensors.py). 1 Hz, assembled by telemetry's slow tick.
SENSORS_HEALTH = "sensors.health"

# App sessions: app.targets is the ghost (clamped, unramped); app.log is cumulative
# like operation.log; app.frames holds the latest JPEG per picture stream (opt-in).
APP_STATE = "app.state"
APP_TARGETS = "app.targets"
APP_LOG = "app.log"
APP_FRAMES = "app.frames"

ALL_TOPICS = [
    STATUS, CONTROL_STATE, ERROR,
    OPERATION_STATE, OPERATION_LOG,
    TACTILE_FORCES, TACTILE_TAXELS,
    JOINTS_MEASURED, JOINTS_ESTIMATE, JOINTS_TARGET, JOINTS_CORRECTION,
    MOTORS_TELEMETRY, MOTORS_FAULTS, STATS, SENSORS_HEALTH,
    APP_STATE, APP_TARGETS, APP_LOG, APP_FRAMES,
]

# Broadcast min-interval in seconds (rate ceiling toward the browser).
MIN_INTERVAL_S = {
    JOINTS_MEASURED: 1.0 / 60.0,
    TACTILE_FORCES: 1.0 / 30.0,
    TACTILE_TAXELS: 1.0 / 30.0,
    APP_TARGETS: 1.0 / 30.0,
    APP_FRAMES: 1.0 / 10.0,
}

BROADCAST_TICK_S = 1.0 / 60.0
