# ORCA UI

Web-based visualization interface for the ORCA Hand tactile sensors. Uses [orca_core](https://github.com/orcahand/orca_core) for hardware communication.

## Installation

```bash
# Install orca_core first (from local checkout or PyPI)
pip install -e /path/to/orca_core

# Then install orca_ui
pip install -e .
```

## Usage

```bash
python -m orca_ui.app
python -m orca_ui.app --config /path/to/orcahand-touch/config.yaml
```

Then open your browser to `http://localhost:5001`

## Features

- **Connection Management**: Connect/disconnect to sensor devices
- **Sensor Status**: View which sensors are connected
- **Taxel Counts**: Display number of taxels for each sensor
- **Force Visualization**: Real-time force vectors displayed as arrows and numerical values
- **Taxel Visualization**: 2D taxel view with magnitude, direction, and arrow display modes
- **Zeroing**: Capture sensor baseline offsets
- **Auto Update**: Continuous monitoring of sensor data via WebSocket
