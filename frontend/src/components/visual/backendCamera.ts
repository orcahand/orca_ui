// The rig's cameras belong to the backend (visual_calibration/rig_cameras.py): the page never
// opens one. Its live view is the backend's preview JPEG, fetched one after the other and painted
// into a canvas whose captureStream() stands in for a camera stream, so a <video> shows it and
// grabFrame() reads it as before. Photos are the backend's own full-resolution stills.

import { useEffect, useState } from "react";
import { cameraPreviewUrl } from "./api";

const PREVIEW_MS = 250; // at most ~4 previews a second
const RETRY_MS = 1500;

const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms));

async function detail(r: Response): Promise<string> {
  try {
    return (await r.json()).detail ?? r.statusText;
  } catch {
    return r.statusText;
  }
}

/** The backend preview of `camera` as a MediaStream while `on`; null until the first frame. */
export function useBackendCamera(
  camera: string | null,
  on: boolean,
  maxSide = 1600,
): { stream: MediaStream | null; size: [number, number] | null; error: string | null } {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [size, setSize] = useState<[number, number] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!camera || !on) return;
    let alive = true;
    let opened: MediaStream | null = null;
    const canvas = document.createElement("canvas");
    const loop = async () => {
      while (alive) {
        const t0 = performance.now();
        try {
          const r = await fetch(cameraPreviewUrl(camera, maxSide), { cache: "no-store" });
          if (!r.ok) throw new Error(await detail(r));
          const frame = await createImageBitmap(await r.blob());
          if (!alive) {
            frame.close();
            break;
          }
          if (canvas.width !== frame.width || canvas.height !== frame.height) {
            canvas.width = frame.width;
            canvas.height = frame.height;
            setSize([frame.width, frame.height]);
          }
          canvas.getContext("2d")!.drawImage(frame, 0, 0);
          frame.close();
          if (!opened) {
            opened = canvas.captureStream();
            setStream(opened);
          }
          setError(null);
        } catch (e) {
          if (alive) setError(`camera ${camera}: ${(e as Error).message}`);
          await sleep(RETRY_MS);
        }
        await sleep(Math.max(0, PREVIEW_MS - (performance.now() - t0)));
      }
    };
    void loop();
    return () => {
      alive = false;
      opened?.getTracks().forEach((t) => t.stop());
      setStream(null);
      setSize(null);
    };
  }, [camera, on, maxSide]);

  return { stream, size, error };
}
