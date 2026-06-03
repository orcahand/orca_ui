# ORCA UI

Web-based visualization interface for the ORCA Hand tactile sensors. Uses [orca_core](https://github.com/orcahand/orca_core) for hardware communication.

## Installation

This project uses [uv](https://docs.astral.sh/uv/). `orca_core` is installed automatically from the public GitHub repo —

```bash
# Creates the virtualenv and installs orca_ui + orca_core (from GitHub)
uv sync
```

> Using a local orca_core dev checkout instead? Edit the `[tool.uv.sources]`
> entry in `pyproject.toml` (instructions are in the comment there), then re-run
> `uv sync`.

## Usage

By default, the UI runs for the **right** touch hand:

```bash
uv run python -m orca_ui.app
```

For the **left** touch hand:

```bash
uv run python -m orca_ui.app --side left
```

To use your own **specific config** (e.g. a per-hand calibrated copy), point at it
with `--config`. This overrides `--side`:

```bash
uv run python -m orca_ui.app --config /path/to/orcahand-touch/config.yaml
```

A browser window opens automatically on startup and closes again when you stop
the program (Ctrl-C). If a Chromium-based browser (Chrome/Brave/Edge/Chromium)
is available it opens a dedicated app window; otherwise your default browser is
used (and won't auto-close). Pass `--no-browser` to disable this and open
`http://localhost:5001` yourself.

Right and left have different sensor wiring, so the `--side` you choose (or the
config you pass) must match your hardware. The config supplies the
finger→sensor-id wiring map and the directory where `calibration.yaml` (zeroing
offsets) is read/written; the `--side` defaults load the matching config bundled
with `orca_core`.

### Mock mode (no hardware)

To try the UI without a touch hand connected, run with `--mock`. It simulates
all five fingers with sine-wave signals on both the resultant force vectors and
every taxel:

```bash
uv run python -m orca_ui.app --mock
```

Open the UI and click **Connect** as usual — the port selector is ignored in
mock mode. Useful for UI development, demos, or verifying the install.

## Features

- **Connection Management**: Connect/disconnect to sensor devices
- **Sensor Status**: View which sensors are connected
- **Taxel Counts**: Display number of taxels for each sensor
- **Force Visualization**: Real-time force vectors displayed as arrows and numerical values
- **Taxel Visualization**: 2D taxel view with magnitude, direction, and arrow display modes
- **Zeroing**: Capture sensor baseline offsets
- **Auto Update**: Continuous monitoring of sensor data via WebSocket
