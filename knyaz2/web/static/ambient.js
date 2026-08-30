// Атмосфера — наше процедурное расширение поверх движка.
import { ambientNode } from "./dom.js";
import { world } from "./world.js";
import { context, visibleWorld, withMainContext } from "./viewport.js";
import { cameraApply, perspective, withPerspective } from "./perspective.js";

// Атмосфера — процедурные частицы без новых ресурсов: летящая листва на
// ветру и редкие стайки птиц. Рисуется после объектов и до фильтра
// дня/ночи, поэтому ночью листва темнеет вместе со сценой.
//
// Дым из труб и тени облаков отсюда убраны 12.08.2026 по просьбе тестеров.
// В оригинале нет ни того, ни другого: труб движок не знает вовсе, а
// ползущие пятна облаков читались как блики и спорили с настоящим светом
// (light.js) и настоящими тенями (shadows.js) — а те сняты с движка.
export const ambient = {
  lastTick: 0,
  ticksPerSecond: 24,
  wind: { x: -0.6, y: 0.2, phase: 0 },
  leaves: [],
  nextLeafAt: 0,
  birds: [],
  nextFlockAt: 8,
  time: 0,
};

export const LEAF_COLORS = ["#b5651d", "#c77b28", "#8f4f16", "#a8621e", "#d18a2d"];

// Смена карты: частицы живут в мировых координатах, и старые на новой карте
// оказываются где попало — список чистится целиком.
export function ambientInit() {
  ambient.leaves = [];
  ambient.birds = [];
  ambient.nextLeafAt = ambient.time;
  ambient.nextFlockAt = ambient.time + 8;
}

export function ambientTick(now) {
  if (!ambientNode.checked || !world.map) return false;
  const interval = 1000 / ambient.ticksPerSecond;
  if (now - ambient.lastTick < interval) return false;
  const dt = Math.min(Math.max(now - ambient.lastTick, 0), 200) / 1000;
  ambient.lastTick = now;
  if (dt === 0) return false;
  ambient.time += dt;
  const t = ambient.time;

  // ветер: медленно гуляет, с порывами
  ambient.wind.phase += dt;
  const gust = 1 + 0.6 * Math.sin(t * 0.23) * Math.sin(t * 0.071 + 2);
  ambient.wind.x = (-0.55 + 0.25 * Math.sin(t * 0.11)) * gust;
  ambient.wind.y = (0.18 + 0.1 * Math.cos(t * 0.09)) * gust;

  const visible = visibleWorld();

  // листва в видимой области
  if (t > ambient.nextLeafAt && ambient.leaves.length < 56) {
    ambient.nextLeafAt = t + 0.3 + Math.random() * 0.65;
    const burst = 1 + (Math.random() * 2 | 0);
    for (let i = 0; i < burst; i += 1) {
      ambient.leaves.push({
        x: visible.left + Math.random() * (visible.right - visible.left),
        y: visible.top + Math.random() * (visible.bottom - visible.top) * 0.5,
        life: 0,
        ttl: 4 + Math.random() * 3,
        spin: Math.random() * Math.PI * 2,
        spinSpeed: (Math.random() - 0.5) * 6,
        flutter: Math.random() * Math.PI * 2,
        color: LEAF_COLORS[(Math.random() * LEAF_COLORS.length) | 0],
      });
    }
  }
  for (const leaf of ambient.leaves) {
    leaf.life += dt;
    leaf.flutter += dt * 7;
    leaf.spin += leaf.spinSpeed * dt;
    leaf.x += (ambient.wind.x * 55 + Math.sin(leaf.flutter) * 14) * dt;
    leaf.y += (ambient.wind.y * 55 + 16 + Math.cos(leaf.flutter * 0.7) * 8) * dt;
  }
  ambient.leaves = ambient.leaves.filter((leaf) => leaf.life < leaf.ttl);

  // птицы: редкий пролёт стайки
  if (t > ambient.nextFlockAt && ambient.birds.length === 0) {
    ambient.nextFlockAt = t + 26 + Math.random() * 28;
    const count = 3 + (Math.random() * 4 | 0);
    const baseY = visible.top + Math.random() * (visible.bottom - visible.top) * 0.6;
    for (let i = 0; i < count; i += 1) {
      ambient.birds.push({
        x: visible.left - 80 - Math.random() * 120 - i * 34,
        y: baseY + (i % 2) * 26 + Math.random() * 18,
        vx: 85 + Math.random() * 20,
        vy: 8 + Math.random() * 10,
        wing: Math.random() * Math.PI * 2,
      });
    }
  }
  for (const bird of ambient.birds) {
    bird.x += bird.vx * dt;
    bird.y += bird.vy * dt;
    bird.wing += dt * 14;
  }
  ambient.birds = ambient.birds.filter((bird) =>
    bird.x < visible.right + 400 && bird.y < visible.bottom + 400);

  return true;
}

export function renderAmbient(visible) {
  if (!ambientNode.checked) return;

  // листва
  for (const leaf of ambient.leaves) {
    const fade = Math.min(1, leaf.life * 2, (leaf.ttl - leaf.life) * 1.5);
    context.save();
    //: Лист летит сам по себе, якорь у него собственный.
    if (perspective.on) cameraApply(context, leaf.x, leaf.y);
    context.translate(leaf.x, leaf.y);
    context.rotate(leaf.spin);
    context.globalAlpha = 0.85 * fade;
    context.fillStyle = leaf.color;
    context.fillRect(-2.4, -1.3, 4.8, 2.6);
    context.restore();
  }
  context.globalAlpha = 1;

  // Птицы и их тени.
  //
  // ТЕНЬ КЛАДЁТСЯ МИМО СЛОЯ СЦЕНЫ, и это не украшательство. Слой, в котором
  // идут объекты, пуст на просвет, а фильтр суток заливает его целиком: над
  // полупрозрачным пятном заливка сама становится изображением, и вместо
  // тёмной тени выходит СВЕТЛОЕ пятно. Ровно та же ловушка описана у
  // полупрозрачной копии героя (scene.js) и у тени в помещении
  // (shadows.js::stampMask). Отсюда и «белые тени у птиц»: они появлялись
  // только тогда, когда кадр собирается послойно, то есть при включённом
  // фильтре и живом локальном свете. Настоящие тени движок кладёт на уже
  // отфильтрованный кадр (проход 0x440788) — кладём туда же.
  for (const bird of ambient.birds) {
    //: ПТИЦУ ВЕДЁМ ЗА ЕЁ ТЕНЬЮ. Тень — точка на земле, а сама птица летит
    //: над ней; общий якорь держит их вместе, врозь они разъехались бы.
    withPerspective(context, bird.x - 34, bird.y + 68, () => {
    withMainContext(() => {
      context.save();
      context.fillStyle = "rgba(10, 10, 12, 0.14)";
      context.beginPath();
      context.ellipse(bird.x - 34, bird.y + 68, 11, 4.2, 0, 0, Math.PI * 2);
      context.fill();
      context.restore();
    });
    const flap = Math.sin(bird.wing);
    context.strokeStyle = "rgba(24, 22, 20, 0.85)";
    context.lineWidth = 2.6;
    context.beginPath();
    context.moveTo(bird.x - 10, bird.y - 8 * flap);
    context.quadraticCurveTo(bird.x, bird.y + 4 * flap, bird.x + 10, bird.y - 8 * flap);
    context.stroke();
    });
  }
}
