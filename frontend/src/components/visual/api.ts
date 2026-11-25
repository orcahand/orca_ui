// REST calls of the visual calibration page (orca_ui/api/visual_calibration.py).

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

/** The rig's cameras (config.yaml cameras:): a level at +x, b on the side rail. */
export const CAMS = ["a", "b"] as const;
export type CamId = (typeof CAMS)[number];

export interface Detected {
  camera?: CamId;
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
  // Every camera's CAD pose and solved camera -> rig matrix (OpenCV frame), newer servers.
  cameras?: Partial<
    Record<
      CamId,
      {
        enabled: boolean;
        cad: { position: number[]; look_at: number[] } | null;
        solved: Mat4 | null;
      }
    >
  >;
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

export interface RigCameraInfo {
  enabled: boolean;
  mount: (CameraMount & { azimuth?: number }) | null;
  nominal: { position: number[]; look_at: number[] } | null; // CAD pose, rig frame mm
  azimuth: number;
  resolution: [number, number] | null;
  serial: string | null; // its USB serial: the camera's identity
  rotation: 0 | 90 | 180 | 270; // clockwise display turn that shows the rig's up as up
  calibrated: { lens: boolean; pose: boolean };
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
  // Newer servers: every camera, and the enabled ones in order (a first).
  cameras?: Partial<Record<CamId, RigCameraInfo>>;
  active_cameras?: CamId[];
  letters: Record<string, string>;
  swap_angle: number; // where the plate parks to swap the object for the hand
  rig_board: { usb_serial: string | null; devices: string[] }; // the turntable's board: never the hand's
  mock_turntable: boolean;
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
  camera?: CamId; // the camera of this frame (several calibrated cameras)
  view_cameras?: CamId[];
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
  camera?: CamId;
  cameras?: Partial<Record<CamId, CameraControls>>; // cam=all
  configured?: boolean;
  set?: Record<string, number | number[]>;
  controls?: Record<string, number | number[]>;
}

type UV = [number, number];
type Mat4 = number[][];

/** What the rig model expects the camera to see at a plate angle; pixels in the raw camera image. */
export interface ModelOverlay {
  angle: number;
  camera?: CamId;
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
  stop_deg: number;
  camera?: CamId; // missing: camera a
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

/** Which rig camera a browser frame shows, from stills taken by each camera's USB serial. */
export interface CameraIdentity {
  camera: CamId | null; // null: not sure
  claim: CamId | null;
  scores: Partial<Record<CamId, number>>;
  errors: Partial<Record<CamId, string>>;
  verified: boolean;
  mock?: boolean; // --mock: no rig cameras to compare with
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

// ---- 0 · Setup (orca_ui/api/rig_setup.py, docs/rig-setup.md)

export type SetupStatus = "ok" | "warn" | "error" | "not run";

/** A finding with its fix (visual_calibration.checks.warning). */
export interface SetupWarning {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  fix: string;
  values: Record<string, unknown>;
}

export interface UsbCamera {
  serial: string | null;
  name: string | null;
  bus: number;
  ports: number[];
  link_mbps: number | null;
  usb3: boolean | null;
  opencv_index: number | null;
  camera: CamId | null; // the mount whose serial it has; null: not assigned yet
}

export interface UsbState {
  status: SetupStatus;
  cameras: UsbCamera[];
  warnings: SetupWarning[];
  banner: SetupWarning[]; // USB 2 links of enabled (or unassigned) cameras: every step shows these
  active_cameras: CamId[];
}

export interface TurntableSetup {
  status: SetupStatus;
  calibrated: boolean;
  board: { port: string; usb_serial: string | null; motor_id: number; model: string; baudrate: number } | null;
  mine?: boolean;
  mock?: boolean;
  warnings: SetupWarning[];
  state?: Turntable;
}

/** One camera's pose from a single view of the tower (setup.single_view_pose). */
export interface ViewPose {
  radius_mm: number;
  height_mm: number;
  tilt_down_deg: number;
  aim_off_axis_deg: number;
  aim_height_mm: number;
  image_roll_deg: number;
  rms_px: number;
  corners: number;
  tiles: string[];
}

export interface IdentifyResult {
  status: SetupStatus;
  cameras: {
    serial: string;
    configured_as: CamId | null;
    usb3: boolean | null;
    pose?: ViewPose | null;
    tiles?: number;
    image?: string; // base64 JPEG
    size?: [number, number];
    error?: string;
  }[];
  identify: {
    assignment: Partial<Record<CamId, string>>;
    confident: boolean;
    margin: number | null;
    unseen: string[];
  };
  before: Partial<Record<CamId, string | null>>;
  disagree: boolean;
  saved: boolean;
  parked_at: number | null;
  nominal: Partial<Record<CamId, { radius_mm: number; height_mm: number; tilt_down_deg: number }>>;
}

export interface Placement {
  camera: CamId;
  ok: boolean;
  found: { distance: number; height: number; tilt: number };
  want: { distance: number; height: number; tilt: number };
  advice: string[];
  lock: string | null;
  holes: Partial<Record<"distance" | "height", number | null>>;
}

export interface AlignResult {
  camera: CamId;
  size: [number, number];
  tiles: string[];
  pose: ViewPose | null;
  ok: boolean;
  placement: Placement | null;
  advice: string[];
  status?: SetupStatus;
  locked?: boolean;
}

export interface SetupJob {
  id: string;
  kind: "exposure" | "focus" | "tour";
  camera: CamId | null;
  state: "running" | "done" | "failed" | "cancelled";
  progress: number;
  note: string;
  result: Record<string, unknown> | null;
  error: string | null;
  started: number;
  ended: number | null;
}

export type SetupItem = { status: SetupStatus; at?: string; [key: string]: unknown };
export type SetupPerCam = { status: SetupStatus; cameras: Partial<Record<CamId, SetupItem>> };

export interface SetupSummary {
  items: {
    usb: SetupItem & { live: UsbState };
    turntable: SetupItem;
    identify: SetupItem;
    align: SetupPerCam;
    exposure: SetupPerCam;
    focus: SetupPerCam;
    tour: SetupItem;
  };
  ready: boolean;
  blockers: string[];
  cameras: CamId[];
  jobs: SetupJob[];
}

export const setupApi = {
  summary: () => call<SetupSummary>("/setup"),
  usb: (fresh = false) =>
    call<UsbState>("/setup/usb", fresh ? { method: "POST" } : undefined),
  turntable: () => call<TurntableSetup>("/setup/turntable", { method: "POST" }),
  identify: () => call<IdentifyResult>("/setup/identify", { method: "POST" }),
  saveIdentity: (assignment: Partial<Record<CamId, string>>) =>
    call<{ status: SetupStatus }>("/setup/identify/save", json({ assignment })),
  align: (cam: CamId) => call<AlignResult>(`/setup/align?cam=${cam}`),
  alignCheck: (cam: CamId, locked: boolean) =>
    call<AlignResult>(`/setup/align/check?cam=${cam}&locked=${locked}`, {
      method: "POST",
    }),
  keepHole: (cam: CamId, key: string, value: number) =>
    call<{ ok: boolean }>("/setup/mount", json({ cam, key, value })),
  exposure: (cam: CamId) =>
    call<SetupJob>(`/setup/exposure?cam=${cam}`, { method: "POST" }),
  focus: (cam: CamId) =>
    call<SetupJob>(`/setup/focus?cam=${cam}`, { method: "POST" }),
  tour: () => call<SetupJob>("/setup/tour", { method: "POST" }),
  // Stream one camera for a while so its white LED lights: which BRIO is which, by eye.
  light: (who: { cam: CamId } | { serial: string }, seconds = 10) =>
    call<{ camera: CamId | null; serial: string; seconds: number; remaining_s: number }>(
      `/setup/light?${"cam" in who ? `cam=${who.cam}` : `serial=${encodeURIComponent(who.serial)}`}&seconds=${seconds}`,
      { method: "POST" },
    ),
  job: (id: string) => call<SetupJob>(`/setup/jobs/${id}`),
  cancel: (id: string) =>
    call<SetupJob>(`/setup/jobs/${id}/cancel`, { method: "POST" }),
};

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
  createSession: (step: SessionKind, handTurned = false, hold = false) =>
    call<Session>("/sessions", json({ step, hand_turned: handTurned, hold })),
  // verify: the server refuses the photo unless camera `cam` (by its serial) shows the same view.
  addPhoto: (id: string, stop: number, image: Blob, cam: CamId = "a", verify = false) =>
    call<Detected & { photo: PhotoEntry }>(
      `/sessions/${id}/photos?stop=${stop}&cam=${cam}${verify ? "&verify=true" : ""}`,
      { method: "POST", body: image },
    ),
  detect: (image: Blob, cam: CamId = "a") =>
    call<Detected>(`/detect?cam=${cam}`, { method: "POST", body: image }),
  identify: (frame: Blob, claim: CamId) =>
    call<CameraIdentity>(`/camera/identify?claim=${claim}`, {
      method: "POST",
      body: frame,
    }),
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
  // cad: the nominal mount pose, lens and tile seats even when calibrated (the setup's ghost).
  overlay: (angle: number, rotation: number, cam: CamId = "a", cad = false) =>
    call<ModelOverlay>(
      `/overlay?angle=${angle}&rotation=${rotation}&cam=${cam}${cad ? "&source=cad" : ""}`,
    ),
  status: () => call<CalStatus>("/status"),
  // cam "all": every enabled camera (409 names each one that differs).
  cameraCheck: (cam: CamId | "all" = "all") =>
    call<CameraControls>(`/camera/uvc?cam=${cam}`),
  liveFit: (
    frame: Blob,
    angle: number,
    joints: Record<string, number>,
    source: string,
    solveJoints = false,
    search = false,
    cam: CamId = "a",
  ) =>
    call<LiveFit>(
      `/live-fit/frame?angle=${angle}&source=${encodeURIComponent(source)}&joints=${encodeURIComponent(JSON.stringify(joints))}&solve_joints=${solveJoints}&search=${search}&cam=${cam}`,
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
  cameraSet: (cam: CamId | "all" = "all") =>
    call<CameraControls>(`/camera/uvc?cam=${cam}`, { method: "POST" }),
  twin: () => call<TwinInfo>("/twin"),
  rigPresence: () => call<RigPresence>("/rig/presence"),
  rigScan: () => call<RigPresence>("/rig/scan", { method: "POST" }),
  park: () => call<Turntable>("/turntable/park", { method: "POST" }),
  twinState: (angle?: number) =>
    call<TwinState>(
      `/twin/state${angle === undefined ? "" : `?angle=${angle}`}`,
    ),
};

export const twinTileUrl = (name: string) =>
  `${BASE}/twin/tiles/${encodeURIComponent(name)}.png`;

/** A still of the camera taken by its USB serial (raw, unturned JPEG). */
export const cameraStillUrl = (cam: CamId, maxSide = 960) =>
  `${BASE}/camera/still?cam=${cam}&max_side=${maxSide}`;

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
