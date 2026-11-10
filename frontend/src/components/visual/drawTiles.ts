// Shared by the visual-calibration page and the dashboard's rig camera.
import type { ModelOverlay } from "./api";

type LayerStyle = { color: string; opacity: number };

// The tiles the model expects, in raw camera pixels: facing ones as outline and
// checker grid, the rest dashed and faint, each with its letter.
export function drawTiles(
  ctx: CanvasRenderingContext2D,
  model: ModelOverlay,
  W: number,
  H: number,
  a: number,
  w: number,
  h: number,
  px: number,
  { color: accent, opacity }: LayerStyle,
  letters: Record<string, string>,
) {
  const mx = W / model.lens.size[0];
  const my = H / model.lens.size[1];
  const at = ([u, v]: [number, number]): [number, number] => [
    u * mx - W / 2,
    v * my - H / 2,
  ];
  ctx.strokeStyle = accent;
  ctx.lineWidth = 1.25 * px;
  ctx.lineJoin = "round";
  for (const t of model.tiles) {
    ctx.globalAlpha = (t.facing ? 0.95 : 0.4) * opacity;
    ctx.setLineDash(t.facing ? [] : [5 * px, 4 * px]);
    ctx.beginPath();
    t.outline.forEach((p, i) =>
      i ? ctx.lineTo(...at(p)) : ctx.moveTo(...at(p)),
    );
    ctx.closePath();
    ctx.stroke();
    if (!t.facing) continue;
    ctx.globalAlpha = 0.6 * opacity;
    ctx.lineWidth = 0.75 * px;
    ctx.beginPath();
    for (const seg of t.grid) {
      if (!seg) continue;
      ctx.moveTo(...at(seg[0]));
      ctx.lineTo(...at(seg[1]));
    }
    ctx.stroke();
    ctx.lineWidth = 1.25 * px;
  }
  ctx.setLineDash([]);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.font = `700 ${Math.round(15 * px)}px 'Space Mono', monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = accent;
  for (const t of model.tiles) {
    const letter = letters[t.tile];
    if (!letter) continue;
    const [x, y] = at([
      t.outline.reduce((s, p) => s + p[0], 0) / 4,
      t.outline.reduce((s, p) => s + p[1], 0) / 4,
    ]);
    ctx.globalAlpha = (t.facing ? 1 : 0.5) * opacity;
    ctx.fillText(
      letter,
      w / 2 + x * Math.cos(a) - y * Math.sin(a),
      h / 2 + x * Math.sin(a) + y * Math.cos(a),
    );
  }
  ctx.globalAlpha = 1;
  ctx.setTransform(1, 0, 0, 1, w / 2, h / 2);
  ctx.rotate(a);
}

