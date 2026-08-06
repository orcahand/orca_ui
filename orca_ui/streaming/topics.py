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

# Teleoperation. teleop.targets streams the retargeter's (clamped) output in
# preview AND engaged — the 3D ghost renders raw intent while joints.target
# carries the post-arbiter ramped command. teleop.log is cumulative like
# operation.log; teleop.preview carries base64 JPEG camera frames (opt-in
# subscription on the frontend).
TELEOP_STATE = "teleop.state"
TELEOP_TARGETS = "teleop.targets"
TELEOP_LOG = "teleop.log"
TELEOP_PREVIEW = "teleop.preview"

# Fetching + building the orca_teleop checkout. Separate from teleop.log on
# purpose: that ring belongs to a session and is cleared when one starts, which
# would wipe the install history at the moment the user acts on it — and it
# lives on the teleop manager, which does not exist under --no-teleop.
TELEOP_INSTALL = "teleop.install"
TELEOP_INSTALL_LOG = "teleop.install.log"

ALL_TOPICS = [
    STATUS, CONTROL_STATE, ERROR,
    OPERATION_STATE, OPERATION_LOG,
    TACTILE_FORCES, TACTILE_TAXELS,
    JOINTS_MEASURED, JOINTS_ESTIMATE, JOINTS_TARGET, JOINTS_CORRECTION,
    MOTORS_TELEMETRY, STATS,
    TELEOP_STATE, TELEOP_TARGETS, TELEOP_LOG, TELEOP_PREVIEW,
    TELEOP_INSTALL, TELEOP_INSTALL_LOG,
]

# Broadcast min-interval in seconds (rate ceiling toward the browser).
MIN_INTERVAL_S = {
    JOINTS_MEASURED: 1.0 / 60.0,
    TACTILE_FORCES: 1.0 / 30.0,
    TACTILE_TAXELS: 1.0 / 30.0,
    TELEOP_TARGETS: 1.0 / 30.0,
    TELEOP_PREVIEW: 1.0 / 10.0,
    # uv sync is chatty. The payload is cumulative, so throttling drops
    # snapshots, never lines.
    TELEOP_INSTALL_LOG: 1.0 / 10.0,
}

BROADCAST_TICK_S = 1.0 / 60.0
