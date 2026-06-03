#!/usr/bin/env python3
"""Web-based testing UI for ORCA Sensor Client"""

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

from orca_core.hardware.tactile_client import TactileClient
from orca_ui.taxel_coordinates import get_all_coordinates
from orca_core.utils.utils import read_yaml, update_yaml, auto_detect_port
import argparse
import os
import yaml
import serial.tools.list_ports
import threading
import time

SENSOR_ADAPTER_VID = 0x28E9
SENSOR_ADAPTER_PID = 0x018A

app = Flask(__name__)
app.config['SECRET_KEY'] = 'orca_sensor_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

sensor_client = None
stream_thread = None
stream_thread_running = False
current_mode = 'resultant'  # 'resultant', 'taxels', or 'combined'
finger_to_sensor_id_config = None  # Loaded from --config if provided
config_dir = None  # Set from --config arg directory, for calibration.yaml access

def resolve_port(requested):
    """Resolve the serial port to use.

    If an explicit port is given, use it. Otherwise auto-detect the tactile
    sensor adapter by USB VID (same logic as orca_core's auto_detect_port),
    which is cross-platform (macOS /dev/cu.usbmodem*, Linux /dev/ttyACM*).
    """
    if requested and requested not in ('auto', ''):
        return requested
    detected = auto_detect_port("tactile_sensor")
    if detected:
        return detected
    raise RuntimeError(
        "No tactile sensor adapter found (USB VID 0x28E9). Check that the "
        "sensor is connected with a data cable, or select a port manually."
    )

def get_sensor_client():
    global sensor_client
    if sensor_client is None:
        sensor_client = TactileClient(port=resolve_port(request.args.get('port')))
    return sensor_client

def stream_update_loop():
    """Background thread that reads from auto-stream and emits via websocket."""
    global stream_thread_running, sensor_client, current_mode

    while stream_thread_running:
        try:
            if sensor_client and sensor_client.is_connected:
                if current_mode == 'resultant':
                    forces, ts = sensor_client.get_auto_latest()
                    if forces is not None:
                        socketio.emit('force_update', forces)
                elif current_mode == 'taxels':
                    taxels, ts = sensor_client.get_auto_latest_taxels()
                    if taxels is not None:
                        socketio.emit('taxel_update', taxels)
                elif current_mode == 'combined':
                    forces, taxels, ts = sensor_client.get_auto_latest_all()
                    if forces is not None or taxels is not None:
                        socketio.emit('combined_update', {
                            'forces': forces,
                            'taxels': taxels
                        })
            time.sleep(0.01)  # ~100Hz update rate
        except Exception as e:
            socketio.emit('error', {'message': str(e)})
            time.sleep(0.1)

def start_stream(mode):
    """Start auto-stream with specified mode."""
    global sensor_client, stream_thread, stream_thread_running, current_mode

    # Stop existing stream
    stop_stream()

    current_mode = mode

    # Configure and start auto-stream
    if mode == 'resultant':
        sensor_client.start_auto_stream(resultant=True, taxels=False)
    elif mode == 'taxels':
        sensor_client.start_auto_stream(resultant=False, taxels=True)
    elif mode == 'combined':
        sensor_client.start_auto_stream(resultant=True, taxels=True)

    # Start websocket emission thread
    stream_thread_running = True
    stream_thread = threading.Thread(target=stream_update_loop, daemon=True)
    stream_thread.start()

def stop_stream():
    """Stop auto-stream and emission thread."""
    global sensor_client, stream_thread, stream_thread_running

    stream_thread_running = False
    if stream_thread:
        stream_thread.join(timeout=1)
        stream_thread = None

    if sensor_client and sensor_client.is_connected:
        try:
            sensor_client.stop_auto_stream()
        except Exception:
            pass

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/ports')
def list_ports():
    ports = serial.tools.list_ports.comports()
    result = []
    for p in ports:
        is_sensor = (p.vid == SENSOR_ADAPTER_VID and p.pid == SENSOR_ADAPTER_PID)
        if p.vid is not None:
            result.append({
                'device': p.device,
                'description': p.description,
                'is_sensor_adapter': is_sensor,
            })
    result.sort(key=lambda x: (not x['is_sensor_adapter'], x['device']))
    return jsonify(result)

@app.route('/api/connect', methods=['POST'])
def connect():
    try:
        data = request.json
        port = resolve_port(data.get('port'))
        mode = data.get('mode', 'resultant')
        global sensor_client, current_mode

        if sensor_client and sensor_client.is_connected:
            stop_stream()
            sensor_client.disconnect()

        sensor_client = TactileClient(port=port, finger_to_sensor_id=finger_to_sensor_id_config)
        sensor_client.connect()

        # Load saved sensor offsets if config was provided
        if config_dir:
            calib_path = os.path.join(config_dir, 'calibration.yaml')
            calib_data = read_yaml(calib_path)
            if calib_data and 'sensor_offsets' in calib_data:
                sensor_client.set_taxel_offsets(calib_data['sensor_offsets'])

        # Start streaming with requested mode
        start_stream(mode)

        # Get configuration for response
        config = sensor_client.get_tactile_configuration()

        socketio.emit('connection_status', {'connected': True, 'mode': mode})
        return jsonify({
            'success': True,
            'message': f'Connected to {port}',
            'mode': mode,
            'config': {
                'active_sensors': config.active_sensors if config else [],
                'num_taxels': config.num_taxels if config else {}
            }
        })
    except Exception as e:
        socketio.emit('connection_status', {'connected': False, 'error': str(e)})
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    try:
        global sensor_client
        stop_stream()
        if sensor_client and sensor_client.is_connected:
            sensor_client.disconnect()
        socketio.emit('connection_status', {'connected': False})
        return jsonify({'success': True, 'message': 'Disconnected'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/mode', methods=['POST'])
def set_mode():
    """Change the streaming mode."""
    try:
        global sensor_client, current_mode
        data = request.json
        mode = data.get('mode', 'resultant')

        if mode not in ('resultant', 'taxels', 'combined'):
            return jsonify({'success': False, 'message': f'Invalid mode: {mode}'}), 400

        if not sensor_client or not sensor_client.is_connected:
            return jsonify({'success': False, 'message': 'Not connected'}), 400

        start_stream(mode)
        socketio.emit('mode_changed', {'mode': mode})
        return jsonify({'success': True, 'mode': mode})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/zero', methods=['POST'])
def zero():
    """Capture current sensor readings as zero baseline."""
    try:
        global sensor_client
        if not sensor_client or not sensor_client.is_connected:
            return jsonify({'success': False, 'message': 'Not connected'}), 400

        offsets = sensor_client.capture_taxel_offsets(num_samples=100)

        if config_dir:
            calib_path = os.path.join(config_dir, 'calibration.yaml')
            update_yaml(calib_path, 'sensor_offsets', offsets)

        return jsonify({'success': True, 'message': 'Sensor offsets captured and applied'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/clear_zero', methods=['POST'])
def clear_zero():
    """Clear sensor zeroing offsets."""
    try:
        global sensor_client
        if not sensor_client or not sensor_client.is_connected:
            return jsonify({'success': False, 'message': 'Not connected'}), 400

        sensor_client.clear_taxel_offsets()
        return jsonify({'success': True, 'message': 'Sensor offsets cleared'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/status')
def status():
    client = get_sensor_client()
    if not client.is_connected:
        return jsonify({'connected': False})

    out = {'connected': True, 'mode': current_mode}
    errors = []

    try:
        out['sensors'] = client.read_connected_sensors()
    except Exception as e:
        errors.append(f"read_connected_sensors: {e}")

    try:
        out['taxels'] = client.read_num_taxels()
    except Exception as e:
        errors.append(f"read_num_taxels: {e}")

    try:
        out['auto_data_type'] = client.read_auto_data_type()
    except Exception as e:
        errors.append(f"read_auto_data_type: {e}")

    # Get stream stats
    try:
        stats = client.get_auto_stats()
        out['stream_stats'] = {
            'frames_ok': stats.frames_ok,
            'parse_ok': stats.parse_ok,
            'parse_errors': stats.parse_errors
        }
    except Exception:
        pass

    out['status_ok'] = (len(errors) == 0)
    if errors:
        out['errors'] = errors

    return jsonify(out)


@app.route('/api/forces')
def forces():
    try:
        client = get_sensor_client()
        if not client.is_connected:
            return jsonify({'error': 'Not connected'}), 400
        forces = client.read_resultant_force()
        return jsonify(forces)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/taxel_coordinates')
def taxel_coordinates():
    """Return taxel coordinates for all fingers."""
    return jsonify(get_all_coordinates())


@app.route('/api/refresh')
def refresh():
    try:
        client = get_sensor_client()
        if not client.is_connected:
            return jsonify({'connected': False})

        connected = client.read_connected_sensors()
        taxels = client.read_num_taxels()
        auto_data = client.read_auto_data_type()
        forces = client.read_resultant_force()

        return jsonify({
            'connected': True,
            'sensors': connected,
            'taxels': taxels,
            'auto_data_type': auto_data,
            'forces': forces,
            'mode': current_mode
        })
    except Exception as e:
        return jsonify({'connected': False, 'error': str(e)}), 400

@socketio.on('connect')
def handle_connect():
    emit('connected', {'data': 'Connected to WebSocket'})

@socketio.on('disconnect')
def handle_disconnect():
    pass

def default_config_path(side):
    """Path to the orca_core-bundled touch-hand config for the given side."""
    import orca_core
    return os.path.join(os.path.dirname(orca_core.__file__),
                        'models', 'v2', f'orcahand_touch_{side}', 'config.yaml')


def main():
    parser = argparse.ArgumentParser(description='ORCA Tactile Sensor UI')
    parser.add_argument('--side', choices=['right', 'left'], default='right',
                        help="Which touch hand to use (default: right). Selects the "
                             "matching sensor wiring from the orca_core bundled config.")
    parser.add_argument('--config', type=str, default=None,
                        help='Path to a hand config.yaml (or the folder containing it), '
                             'overriding --side. Used for the finger->sensor wiring map '
                             'and calibration.yaml location.')
    args = parser.parse_args()

    global config_dir, finger_to_sensor_id_config

    if args.config:
        # Accept either a config.yaml file or the directory containing it.
        config_path = args.config
        if os.path.isdir(config_path):
            config_path = os.path.join(config_path, 'config.yaml')
    else:
        config_path = default_config_path(args.side)

    if not os.path.isfile(config_path):
        parser.error(f"Config not found: {config_path}\n"
                     f"Pass --config <file-or-folder> explicitly, or check your "
                     f"orca_core install.")

    config_dir = os.path.dirname(os.path.abspath(config_path))
    with open(config_path) as f:
        config_data = yaml.safe_load(f)
    sensors_cfg = config_data.get('sensors', {})
    mapping = sensors_cfg.get('finger_to_sensor_id')
    if mapping:
        finger_to_sensor_id_config = mapping
        source = args.config and config_path or f"{args.side} hand"
        print(f"Loaded sensor mapping ({source}): {finger_to_sensor_id_config}")
    else:
        print(f"Warning: no 'sensors.finger_to_sensor_id' in {config_path}; "
              f"using TactileClient defaults.")

    socketio.run(app, host='0.0.0.0', port=5001, debug=True, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    main()
