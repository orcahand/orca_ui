// REST calls of the visual calibration page (orca_ui/api/visual_calibration.py).

import { noteMissing } from "./missing";

export interface Detection {
  tile: string;
  ids: number[];
  uv: [number, number][];
  markers: number;
}

/** Which clockwise display turn puts the tower up, read from the tiles' corner grids. */
export interface Orientation {
  rotation: 0 | 90 | 180 | 270;
  agreement: number; // 0..1, how well the tiles agree
  up_raw: [number, number]; // the tower's up in the raw frame
}

export interface Detected {
  size: [number, number];
  detections: Detection[];
  orientation: Orientation | null;
}

export type Severity = "info" | "warning" | "error";

/** One finding of a solve or of the rig state (visual_calibration/checks.py). */
export interface CalWarning {
  code:
    | "tower_tilt"
    | "tower_offset"
    | "mounting_found"
    | "mounting_unusual"
    | "plate_direction"
    | "residual_high"
    | "weak_tiles"
    | "stop_coverage"
    | "camera_off_cad"
    | "camera_height"
    | "stop_angle"
    | "turntable_uncalibrated"
    | "note";
  severity: Severity;
  message: string;
  fix: string;
  values: Record<string, unknown>;
}

export interface Mounting {
  yaw: number; // the tower's turn on the plate, deg (snapped to the connector's 0/90/180/270)
  measured: number;
  side0_stop: number; // plate angle at which side 0 faces the camera
  direction: number;
  direction_known: boolean;
  consistency: number;
  snapped: boolean;
  source: string;
}

/** 1b: the tower's pose on the turning axis; its height is held at the CAD. */
export interface TowerPose {
  tilt: [number, number]; // deg about x, y
  offset: [number, number]; // mm
  yaw: number; // deg, object -> plate
  yaw_from_mounting: number;
  height: string;
}

export type StepStatus =
  "done" | "missing" | "none" | "empty" | "photos" | "solved" | "applied";

export interface CalStep {
  id: "motor" | "camera" | "rotation" | "hand";
  title: string;
  status: StepStatus;
  time: string | null;
  session?: string | null;
  note?: string;
  numbers: {
    residual_px?: number | null;
    target_px?: number;
    frames?: number;
    corners?: number;
    tower?: TowerPose | null;
    travel_deg?: number;
    travel_error_deg?: number;
    homing_spread_deg?: number;
    stops?: number;
  };
  warnings: CalWarning[];
}

export interface CalStatus {
  rig: string;
  version: string;
  calibrated_at: string | null;
  mounting: Mounting | null;
  steps: CalStep[];
  turntable: Turntable;
}

/** Shea's twin.json (orca_files calibration_rig/twin/): rig-frame mm, z up; meshes at twinFileUrl(name). */
export interface TwinInfo {
  frame: string;
  mesh_units: string;
  placement: string;
  groups: Record<string, string>;
  camera: {
    optical_centre: number[];
    view_dir: number[];
    body_up: number[];
    tilt_deg: number;
  };
  tile_seats: Record<string, { corner: number[]; rpy: number[] }>;
  parts: unknown;
  files: string[];
}

/** Live pose of the twin; matrices are 4×4, rig frame, mm (world = group · transform · vertex). */
export interface TwinState {
  angle: number | null;
  angle_source: "turntable" | "query" | "none";
  mounting: Mounting | null;
  tower: TowerPose | null;
  groups: { rotor: Mat4; object_cad: Mat4; object_solved: Mat4 | null };
  camera: {
    cad: { position?: number[]; look_at?: number[]; twin?: TwinInfo["camera"] };
    solved: Mat4 | null; // camera -> rig, OpenCV camera frame
    frame: string;
  };
  axis: {
    cad: { point: number[]; direction: number[] };
    solved: {
      point_object: number[];
      direction_object: number[];
      tilt_deg: number[];
      offset_mm: number[];
    } | null;
  };
  twin_available: boolean;
  // Newer servers (docs/rig-dashboard.md): the hand on the plate, rig frame, mm.
  hand?: { plate_from_hand: Mat4; rig_from_hand: Mat4 };
  swap_angle?: number;
  travel?: number;
}

/** The calibration rig as orca-ui found it (docs/rig-dashboard.md). */
export interface RigPresence {
  present: boolean;
  connected: boolean;
  port: string | null;
  usb_serial: string | null;
  reason: string;
  model: string | null;
  identity_claim: string | null;
  warnings: string[];
  autodetect: boolean;
  turntable: Turntable;
  hand_blocker: string | null;
}

export interface CameraMount {
  distance: number;
  height: number;
  tilt: number;
}

export interface RigInfo {
  rig: string;
  version: string;
  stops: number[];
  travel: number;
  side0_stop: number | null; // found from the photos once calibrated, else the CAD
  mounting: Mounting | null;
  mountings: number[];
  coverage_warnings: string[];
  tiles: string[];
  reference_tile: string | null;
  camera_mount: CameraMount | null;
  letters: Record<string, string>;
  swap_angle: number; // where the plate parks to swap the object for the hand
  rig_board: { usb_serial: string | null; devices: string[] }; // the turntable's board: never the hand's
  mock_turntable: boolean;
  cameras: string[]; // the enabled cameras ("a" above, "b" on the side rail): every photo is from all of them
}

/** The camera's UVC controls against the rig config (409 = they differ, or could not be set). */
export interface LiveFit {
  delta: { rotation_deg: number[]; translation_mm: number[] };
  cost_px: { cad: number; fit: number };
  iterations: number;
  angle: number;
  size: [number, number];
  outlines: { cad: [number, number][][]; fit: [number, number][][] };
  joints_source: string;
  joints_used: string[];
  joints_unknown: string[];
  seconds: number;
  solve_joints: boolean;
  plate_from_hand: number[][]; // the estimated mount: URDF base in the plate frame, mm
  joints_deg: Record<string, number>; // the estimate (URDF names and convention)
  joint_table: JointEstimate[];
  suggest: { angle: number; joints: string[]; better: boolean } | null;
  views: number[];
  segmentation: { png: string; box: [number, number, number, number] } | null;
}

export interface JointEstimate {
  name: string;
  deg: number;
  std_deg: number | null;
  spread_deg: number | null;
  seen: number; // 0..1: how much of the joint's motion this view shows
  confidence: "good" | "fair" | "poor";
  ambiguous: boolean;
  at_limit: boolean;
}

export interface CameraControls {
  ok: boolean;
  configured?: boolean;
  set?: Record<string, number | number[]>;
  controls?: Record<string, number | number[]>;
  cameras?: Record<string, { set: Record<string, number | number[]>; controls: Record<string, number | number[]> }>;
}

/** The backend's camera preflight (visual_calibration/rig_cameras.py): which stream is which camera. */
export interface CameraPreflight {
  indices: Record<string, number>;
  identified_by: "serial" | "index" | "mock";
  reordered?: Record<string, string>;
  tiles?: Record<string, { height_mm: number; expected_mm: number; tiles: number; corners: number }>;
  at: string;
}

/** One stop's photos, one per camera, stored by the backend from its own stills. */
export interface Captured {
  stop: number;
  size: [number, number];
  cameras: Record<string, Omit<Detected, "size"> & { photo: PhotoEntry }>;
}

type UV = [number, number];
type Mat4 = number[][];

/** What the rig model expects the camera to see at a plate angle; pixels in the raw camera image. */
export interface ModelOverlay {
  angle: number;
  source: { lens: string; camera: string; tiles: string; axis: string };
  lens: {
    fx: number;
    fy: number;
    cx: number;
    cy: number;
    size: [number, number];
    distortion: number[];
  };
  camera_from_plate: Mat4;
  plate_from_hand: Mat4;
  tiles: {
    tile: string;
    facing: boolean;
    outline: UV[];
    grid: ([UV, UV] | null)[];
  }[];
}

export interface Turntable {
  connected: boolean;
  mock: boolean;
  homed: boolean;
  angle: number | null;
  busy: boolean;
  port: string | null;
  motor_id: number | null;
  calibrated: boolean; // turntable_calibration.yaml exists: motor position ↔ plate angle known
  zero_from: "homing" | "calibration" | null;
  torque?: boolean; // off after any error: the plate turns freely, its angle is kept
}

/** The motor calibration (turntable_calibration.yaml). */
export interface MotorCalibration {
  zero_motor_deg: number;
  zero_in_turn_ticks: number;
  travel_deg: number;
  travel_error_deg: number;
  homing_spread_deg: number;
  stops_motor_deg: Record<string, number>;
}

export type SessionKind = "camera" | "rotation" | "hand";

export interface PhotoEntry {
  name: string;
  camera?: string; // missing: camera "a"
  stop_deg: number;
  tiles: number;
  corners: number;
  captured_at: string;
}

export interface Fit {
  reprojection_px: number;
  points: number;
  photos?: number;
  stops_used?: number;
}

/** camera (1a): lens + camera_fit; rotation (1b): also camera, axis, stop_angle_corrections, fit. */
export interface SolveResult {
  lens: {
    image_size: number[];
    fx: number;
    fy: number;
    cx: number;
    cy: number;
    distortion: number[];
    reprojection_px: number;
  };
  camera_fit?: Fit;
  fit?: Fit;
  camera?: { translation: number[]; rotation: number[] };
  axis?: { tilt: number[]; offset: number[] };
  stop_angle_corrections?: Record<string, number>;
  per_photo_px: Record<string, number>;
  per_tile_px: Record<string, number>;
}

export interface Session {
  id: string;
  step: SessionKind;
  created: string;
  hand_turned: boolean;
  image_size: [number, number] | null;
  photos: PhotoEntry[];
  result: SolveResult | null;
}

export interface SessionListItem {
  id: string;
  step: SessionKind;
  created: string;
  photos: number;
  solved: boolean;
}

export interface LutState {
  available: boolean;
  summary: string | null;
  heldout: Record<string, { before: number | null; after: number | null }> | null;
  tips: Record<string, { before: number; after: number }> | null;
  touch: Record<string, Record<string, number>>;
  mount: number[][] | null; // plate_from_hand the study measured
}

export interface LutCommand {
  command: Record<string, number>;
  reached: Record<string, number> | null; // what the hand really reaches with it (the table)
}

/** One step of the hand run (hand_study.run_hand.progress). */
export interface HandRunStep {
  name: string;
  label: string;
  state: "done" | "running" | "todo";
  poses?: number; // a block's poses (its limit in a trial)
  taken?: number;
}

/** The rig's hand run, as the console's child process and from its run folder. */
export interface HandRun {
  // ended: it stopped without the night finishing (a dry run only lists its steps)
  state: "idle" | "running" | "done" | "failed" | "stopped" | "ended";
  hand?: string;
  dry?: boolean;
  started?: number;
  ended?: number | null;
  returncode?: number | null;
  stopped?: string | null; // "stopped", "e-stop", "the console shut down"
  reason?: string | null; // why a run failed
  dead_workers?: string[]; // the logs of solve workers that died
  run?: string | null; // its folder under the rig
  log?: string; // the run's output, in the console's state
  log_tail?: string[];
  progress: {
    state: string; // the night's: starting, planned, running, done, aborted
    error: string | null;
    step: string | null;
    steps: HandRunStep[];
    eta_s: number | null;
    photos: Record<string, string>; // camera -> its newest photo, in the run folder
    cut_short: string | null; // the step the night's deadline came before
    recorded: boolean; // this run's fit recorded the ranges
  } | null;
}

/** RMS and max |true - predicted| (deg); null where the check saw no pose of the joint. */
export interface ErrorStats {
  rms: number;
  max: number;
  mean?: number;
  p50?: number;
  p95?: number;
  n?: number;
}

export interface HandRunResults {
  run: string;
  hand: string | null;
  rig: string | null;
  started: string | null;
  poses: number;
  min_span: number | null; // share of a joint's range the motor must have covered to be measured
  joint_ranges: string | null; // the joint_ranges.yaml written, or null when no joint was measured
  gone: string[]; // joints the hand's joint_ranges.yaml held before and no longer does (model range again)
  joints: Record<
    string,
    {
      old: [number, number]; // in force before the run
      new: [number, number]; // the measured one (the old one when not measured)
      measured: boolean; // fitted with enough coverage and recorded
      rejected: string | null; // why a fitted joint was left out (its fit is not a range)
      uncalibrated: boolean; // the joint had no calibration to fit under
      n: number;
      rms: number;
      t_span: [number, number] | null;
    }
  >;
  accuracy: {
    n: number;
    n_all: number;
    before: Record<string, ErrorStats | null>; // per joint, and "all"
    after: Record<string, ErrorStats | null>;
  } | null;
}

/** One check of orca_core's rig doctor (visual_calibration/doctor.py). */
export interface DoctorCheck {
  name: string;
  status: "ok" | "warn" | "error";
  detail: string;
  fix: string | null;
}

export interface Doctor {
  ok: boolean; // no check is an error
  checks: DoctorCheck[];
}

export interface BoardWriter {
  available: boolean;
  tool: string | null;
  reason: string | null;
  looked_in?: string; // where the orca_firmware checkout was looked for, when none was found
}

const BASE = "/api/visual-calibration";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* keep statusText */
    }
    noteMissing(response, detail);
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const visualApi = {
  lut: () => call<LutState>("/lut"),
  lutCommand: (angles: Record<string, number>, useLut: boolean) =>
    call<LutCommand>("/lut/command", json({ angles, use_lut: useLut })),
  rig: () => call<RigInfo>("/rig"),
  sessions: () => call<SessionListItem[]>("/sessions"),
  session: (id: string) => call<Session>(`/sessions/${id}`),
  createSession: (step: SessionKind, handTurned = false) =>
    call<Session>("/sessions", json({ step, hand_turned: handTurned })),
  capture: (id: string, stop: number) =>
    call<Captured>(`/sessions/${id}/capture?stop=${stop}`, { method: "POST" }),
  cameraPreflight: (tiles: boolean) =>
    call<CameraPreflight>("/cameras/preflight", json({ tiles })),
  detect: (image: Blob) =>
    call<Detected>("/detect", { method: "POST", body: image }),
  solve: (id: string) =>
    call<Session>(`/sessions/${id}/solve`, { method: "POST" }),
  apply: (id: string) =>
    call<{ path: string }>(`/sessions/${id}/apply`, { method: "POST" }),
  turntable: () => call<Turntable>("/turntable"),
  // The torque is off whenever the plate stops; hold: only a sweep's (or a capture's) stop keeps it
  // on, and the server drops it soon if no next move comes.
  connect: (torque = false) =>
    call<Turntable>("/turntable/connect", json({ torque })),
  torqueOff: () => call<Turntable>("/turntable/torque-off", { method: "POST" }),
  home: (hold = false) => call<Turntable>("/turntable/home", json({ hold })),
  move: (angle: number, hold = false) =>
    call<Turntable>("/turntable/move", json({ angle, hold })),
  calibrateMotor: () =>
    call<Turntable & { calibration: MotorCalibration }>(
      "/turntable/calibrate",
      { method: "POST" },
    ),
  release: () => call<Turntable>("/turntable/release", { method: "POST" }),
  overlay: (angle: number, rotation: number, camera = "a") =>
    call<ModelOverlay>(
      `/overlay?angle=${angle}&rotation=${rotation}&camera=${encodeURIComponent(camera)}`,
    ),
  status: () => call<CalStatus>("/status"),
  cameraCheck: () => call<CameraControls>("/camera/uvc"),
  liveFit: (
    frame: Blob,
    angle: number,
    joints: Record<string, number>,
    source: string,
    solveJoints = false,
    search = false,
  ) =>
    call<LiveFit>(
      `/live-fit/frame?angle=${angle}&source=${encodeURIComponent(source)}&joints=${encodeURIComponent(JSON.stringify(joints))}&solve_joints=${solveJoints}&search=${search}`,
      { method: "POST", body: frame },
    ),
  liveFitKeepView: () =>
    call<{ views: number }>("/live-fit/keep-view", { method: "POST" }),
  liveFitClearViews: () =>
    call<{ views: number }>("/live-fit/clear-views", { method: "POST" }),
  liveFitReset: () =>
    call<{ ok: boolean }>("/live-fit/reset", { method: "POST" }),
  liveFitFreeze: () =>
    call<{ path: string }>("/live-fit/freeze", { method: "POST" }),
  cameraSet: () => call<CameraControls>("/camera/uvc", { method: "POST" }),
  twin: () => call<TwinInfo>("/twin"),
  rigPresence: () => call<RigPresence>("/rig/presence"),
  rigScan: () => call<RigPresence>("/rig/scan", { method: "POST" }),
  park: () => call<Turntable>("/turntable/park", { method: "POST" }),
  handRun: () => call<HandRun>("/hand-run"),
  handRunStart: (dry = false) => call<HandRun>("/hand-run/start", json({ dry })),
  handRunStop: () => call<HandRun>("/hand-run/stop", { method: "POST" }),
  handRunResults: () =>
    call<{ hand: string; latest: string | null; results: HandRunResults | null }>("/hand-run/results"),
  boardWriter: () => call<BoardWriter>("/board-write"),
  doctor: () => call<Doctor>("/doctor"),
  twinState: (angle?: number) =>
    call<TwinState>(
      `/twin/state${angle === undefined ? "" : `?angle=${angle}`}`,
    ),
};

/** A camera's live view from the backend, a JPEG scaled to maxSide (the page never opens a camera). */
export const cameraPreviewUrl = (camera: string, maxSide: number) =>
  `${BASE}/cameras/${encodeURIComponent(camera)}/preview.jpg?max_side=${maxSide}`;

/** The hand run's newest photo from `camera`; `key` changes with the photo. */
export const handRunPhotoUrl = (camera: string, key: string) =>
  `${BASE}/hand-run/photo/${encodeURIComponent(camera)}.jpg?k=${encodeURIComponent(key)}`;

export const twinTileUrl = (name: string) =>
  `${BASE}/twin/tiles/${encodeURIComponent(name)}.png`;

export const twinFileUrl = (name: string) =>
  `${BASE}/twin/files/${encodeURIComponent(name)}`;

/** The video's current frame (unrotated, as the camera sends it), scaled so its long side is at most maxSide. */
export function grabFrame(
  video: HTMLVideoElement,
  type: "image/png" | "image/jpeg",
  maxSide = Infinity,
): Promise<Blob> {
  const scale = Math.min(
    1,
    maxSide / Math.max(video.videoWidth, video.videoHeight),
  );
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d")!.drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("could not grab a frame"))),
      type,
      0.9,
    ),
  );
}
