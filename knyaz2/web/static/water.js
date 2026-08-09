// Анимированная подложка 256x256 (VA 0x43F46E/0x43F4D9).
// Вода: точное воспроизведение варпа движка (VA 0x43F46E/0x43F4D9).
// Каждый тик обе фазы растут на единицу, как в оригинальном цикле рендера.
import { world } from "./world.js";

export const water = {
  enabled: false,
  size: 256,
  wavePeriod: 128,
  horizontalScroll: false,
  ticksPerSecond: 18,
  wavePhase: 1,
  scrollPhase: 1,
  sourcePixels: null,          // Uint32Array исходного тайла
  displacement: null,          // таблица смещений из синуса
  canvas: null,                // offscreen с текущим кадром
  context: null,
  frame: null,                 // ImageData под запись
  lastTick: 0,
};

export function waterInit(animation, image) {
  const size = water.size;
  const probe = document.createElement("canvas");
  probe.width = size;
  probe.height = size;
  const probeContext = probe.getContext("2d", { willReadFrequently: true });
  probeContext.drawImage(image, 0, 0);
  water.sourcePixels = new Uint32Array(
    probeContext.getImageData(0, 0, size, size).data.buffer.slice(0));
  // konung2.exe: trunc((sin(i*2*pi/128)+1)*524288) >> 16
  water.displacement = new Uint16Array(size);
  for (let i = 0; i < size; i += 1) {
    water.displacement[i] =
      (Math.trunc((Math.sin(i * 3.14159 * 2 * 0.0078125) + 1) * 524288) >> 16) & 0xffff;
  }
  water.wavePeriod = animation.wave_period ?? 128;
  water.horizontalScroll = Boolean(animation.horizontal_scroll);
  water.canvas = document.createElement("canvas");
  water.canvas.width = size;
  water.canvas.height = size;
  water.context = water.canvas.getContext("2d");
  water.frame = water.context.createImageData(size, size);
  water.enabled = true;
  waterRender();
}

export function waterRender() {
  const size = water.size;
  const source = water.sourcePixels;
  const out = new Uint32Array(water.frame.data.buffer);
  const disp = water.displacement;
  const phase = water.wavePhase & (water.wavePeriod - 1);
  const shift = water.horizontalScroll ? (water.scrollPhase & 0xff) : 0;
  for (let y = 0; y < size; y += 1) {
    const xShift = disp[phase + (y & 0x7f)];
    const target = y * size;
    for (let x = 0; x < size; x += 1) {
      // скролл применяется к готовому кадру: читаем со сдвинутого столбца
      const column = (x - shift) & 0xff;
      const sourceY = (y + disp[phase + (column & 0x7f)]) & 0xff;
      const sourceX = (column + xShift) & 0xff;
      out[target + x] = source[sourceY * size + sourceX];
    }
  }
  water.context.putImageData(water.frame, 0, 0);
}

export function waterTick(now) {
  if (!water.enabled || !world.underlay.length) return false;
  const interval = 1000 / water.ticksPerSecond;
  if (now - water.lastTick < interval) return false;
  water.lastTick = now - ((now - water.lastTick) % interval);
  water.wavePhase = (water.wavePhase + 1) & 0xffff;
  water.scrollPhase = (water.scrollPhase + 1) & 0xff;
  waterRender();
  return true;
}
