// Диагностические оверлеи и панель под курсором.
import { debugGroundNode, debugInfoNode, debugObjectsNode } from "./dom.js";
import { world } from "./world.js";
import { cellVisible, context, traceDiamond, view } from "./viewport.js";

export function renderGroundDebug(visible) {
  if (!debugGroundNode.checked) return;
  const grid = world.map.coordinates.ground_grid;
  context.lineWidth = 1 / view.zoom;
  context.font = `${Math.max(8, 10 / view.zoom)}px ui-monospace, monospace`;
  context.textAlign = "center";
  context.textBaseline = "middle";

  for (const cell of world.ground) {
    const x = cell.x;
    const y = cell.y;
    if (!cellVisible(x, y, visible)) continue;
    const missing = cell.asset && world.missingAssets.has(cell.asset);
    const empty = !cell.asset;
    traceDiamond(x, y);
    if (empty) {
      context.fillStyle = "rgba(220, 52, 45, .14)";
      context.strokeStyle = "rgba(255, 92, 80, .58)";
      context.fill();
    } else if (missing) {
      context.fillStyle = "rgba(255, 0, 190, .35)";
      context.strokeStyle = "#ff4bd4";
      context.fill();
    } else if (cell.light) {
      context.strokeStyle = "rgba(255, 205, 72, .85)";
    } else if (cell.tiles.lower != null && cell.tiles.upper != null) {
      context.strokeStyle = "rgba(68, 210, 255, .82)";
    } else {
      context.strokeStyle = "rgba(98, 230, 135, .65)";
    }
    context.stroke();
    if (view.zoom >= 0.72) {
      context.fillStyle = empty ? "rgba(255, 155, 145, .8)" : "rgba(10, 10, 8, .78)";
      context.fillText(`${cell.row}:${cell.col}`, x + grid.tile_width / 2,
        y + grid.tile_height / 2);
    }
  }
}

export function renderObjectDebug(visible) {
  if (!debugObjectsNode.checked) return;
  context.lineWidth = 1.5 / view.zoom;
  context.font = `${Math.max(9, 11 / view.zoom)}px ui-monospace, monospace`;
  context.textAlign = "left";
  context.textBaseline = "top";
  for (const object of world.objects) {
    const main = object.frames?.main;
    if (!main) continue;
    const { draw_x: x, draw_y: y, width, height } = object.bounds;
    if (x > visible.right || y > visible.bottom ||
        x + width < visible.left || y + height < visible.top) continue;
    context.strokeStyle = world.missingAssets.has(main.asset) ? "#ff4bd4" : "#ff9b45";
    context.strokeRect(x, y, width, height);
    context.fillStyle = "rgba(20, 15, 8, .82)";
    context.fillRect(x, y, 122 / view.zoom, 16 / view.zoom);
    context.fillStyle = "#ffd39d";
    context.fillText(`#${object.draw_order} res:${object.resource_slot} s:${object.state}`,
      x + 3 / view.zoom, y + 2 / view.zoom);
  }
}

export function closestGroundCell(point) {
  const grid = world.map.coordinates.ground_grid;
  const estimatedRow = Math.round((point.y - grid.tile_height / 2) / grid.step_y);
  let best = null;
  for (let row = estimatedRow - 2; row <= estimatedRow + 2; row += 1) {
    if (row < 0 || row >= grid.rows) continue;
    const shift = row & 1 ? grid.odd_row_offset : 0;
    const estimatedCol = Math.round((point.x - shift - grid.tile_width / 2) / grid.step_x);
    for (let col = estimatedCol - 1; col <= estimatedCol + 1; col += 1) {
      const cell = world.groundByKey.get(`${row}:${col}`);
      if (!cell) continue;
      const x = cell.x, y = cell.y;
      const distance = Math.abs((point.x - x - grid.tile_width / 2) / (grid.tile_width / 2)) +
        Math.abs((point.y - y - grid.tile_height / 2) / (grid.tile_height / 2));
      if (!best || distance < best.distance) best = { cell, distance };
    }
  }
  return best?.cell ?? null;
}

export function topObjectAt(point) {
  for (let index = world.objects.length - 1; index >= 0; index -= 1) {
    const object = world.objects[index];
    if (!object.frames?.main) continue;
    const { draw_x: x, draw_y: y, width, height } = object.bounds;
    if (point.x >= x && point.x <= x + width &&
        point.y >= y && point.y <= y + height) return object;
  }
  return null;
}

export function updateDebugInfo(point) {
  if (!world.map) return;
  const cell = closestGroundCell(point);
  const object = topObjectAt(point);
  const lines = [];
  if (cell) {
    lines.push(`земля ${cell.row}:${cell.col}`,
      `tiles ${cell.tiles.lower ?? "—"} / ${cell.tiles.upper ?? "—"} · light ${cell.light?.mask ?? "—"}`,
      `asset ${cell.asset ?? "ОШИБКА ДЕКОДЕРА"}`);
  }
  if (object) {
    lines.push(`${object.kind} #${object.draw_order} · record ${object.record_slot}`,
      `resource ${object.resource_slot} · palette ${object.palette} · state ${object.state}`,
      `anchor ${object.bounds.offset_x}, ${object.bounds.offset_y} · sort_y ${object.bounds.sort_y}`,
      `кадры ${Object.keys(object.frames ?? {}).join(", ") || "—"}` +
      (object.lighting?.main_static_palette ? " · интерьер дневной" : ""));
  }
  debugInfoNode.textContent = lines.join("\n") || "В этой точке нет данных";
}
