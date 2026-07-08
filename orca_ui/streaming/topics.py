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
STATS = "stats"

ALL_TOPICS = [
    STATUS, CONTROL_STATE, ERROR,
    OPERATION_STATE, OPERATION_LOG,
    TACTILE_FORCES, TACTILE_TAXELS,
    JOINTS_MEASURED, JOINTS_ESTIMATE, JOINTS_TARGET, JOINTS_CORRECTION,
    MOTORS_TELEMETRY, STATS,
]

# Broadcast min-interval in seconds (rate ceiling toward the browser).
MIN_INTERVAL_S = {
    JOINTS_MEASURED: 1.0 / 60.0,
    TACTILE_FORCES: 1.0 / 30.0,
    TACTILE_TAXELS: 1.0 / 30.0,
}

BROADCAST_TICK_S = 1.0 / 60.0
