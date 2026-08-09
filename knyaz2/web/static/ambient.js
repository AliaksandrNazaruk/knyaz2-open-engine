// Атмосфера — наше процедурное расширение поверх движка.
import { ambientNode } from "./dom.js";
import { world } from "./world.js";
import { context, view, visibleWorld } from "./viewport.js";

// Атмосфера — процедурные частицы без новых ресурсов: летящая листва и
// дым из труб на общем ветру, ползущие тени облаков, редкие стайки птиц.
// Всё рисуется после объектов и до фильтра дня/ночи, поэтому ночью эффекты
// темнеют вместе со сценой.
export const ambient = {
  lastTick: 0,
  ticksPerSecond: 24,
  wind: { x: -0.6, y: 0.2, phase: 0 },
  leaves: [],
  nextLeafAt: 0,
  smoke: [],
  chimneys: [],                // {x, y, nextPuffAt}
  clouds: [],
  birds: [],
  nextFlockAt: 8,
  time: 0,
};

export const LEAF_COLORS = ["#b5651d", "#c77b28", "#8f4f16", "#a8621e", "#d18a2d"];

export function ambientInit() {
  ambient.clouds = [];
  for (let i = 0; i < 3; i += 1) {
    ambient.clouds.push({
      x: 600 + i * 1400 + Math.random() * 600,
      y: 400 + Math.random() * 2200,
      radius: 280 + Math.random() * 160,
      vx: 9 + Math.random() * 6,
      vy: 2 + Math.random() * 3,
    });
  }
  ambient.chimneys = world.objects
    .filter((object) => object.frames?.roof)
    .map((object) => ({
      x: object.bounds.draw_x + object.bounds.width * 0.52,
      y: object.bounds.draw_y + object.bounds.height * 0.10,
      nextPuffAt: Math.random() * 2,
    }));
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

  // дым: клубы из труб видимых изб
  for (const chimney of ambient.chimneys) {
    if (chimney.x < visible.left || chimney.x > visible.right ||
        chimney.y < visible.top || chimney.y > visible.bottom) continue;
    if (t > chimney.nextPuffAt && ambient.smoke.length < 110) {
      chimney.nextPuffAt = t + 0.7 + Math.random() * 0.9;
      ambient.smoke.push({
        x: chimney.x + (Math.random() - 0.5) * 3,
        y: chimney.y,
        life: 0,
        ttl: 4.2 + Math.random() * 1.8,
        seed: Math.random() * Math.PI * 2,
      });
    }
  }
  for (const puff of ambient.smoke) {
    puff.life += dt;
    puff.x += (ambient.wind.x * 26 + Math.sin(puff.seed + puff.life * 2) * 4) * dt;
    puff.y -= (16 + 4 * Math.sin(puff.seed)) * dt;
  }
  ambient.smoke = ambient.smoke.filter((puff) => puff.life < puff.ttl);

  // тени облаков ползут по миру
  for (const cloud of ambient.clouds) {
    cloud.x += cloud.vx * dt;
    cloud.y += cloud.vy * dt;
    if (cloud.x - cloud.radius > 4800) cloud.x = -cloud.radius;
    if (cloud.y - cloud.radius > 3100) cloud.y = -cloud.radius;
  }

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

  // тени облаков — мягкие пятна на всей сцене
  for (const cloud of ambient.clouds) {
    if (cloud.x + cloud.radius < visible.left || cloud.x - cloud.radius > visible.right ||
        cloud.y + cloud.radius < visible.top || cloud.y - cloud.radius > visible.bottom) continue;
    const gradient = context.createRadialGradient(
      cloud.x, cloud.y, cloud.radius * 0.15, cloud.x, cloud.y, cloud.radius);
    gradient.addColorStop(0, "rgba(8, 10, 14, 0.13)");
    gradient.addColorStop(0.7, "rgba(8, 10, 14, 0.08)");
    gradient.addColorStop(1, "rgba(8, 10, 14, 0)");
    context.fillStyle = gradient;
    context.fillRect(cloud.x - cloud.radius, cloud.y - cloud.radius,
      cloud.radius * 2, cloud.radius * 2);
  }

  // дым
  for (const puff of ambient.smoke) {
    const k = puff.life / puff.ttl;
    const radius = 2.6 + k * 7.5;
    const alpha = 0.27 * (1 - k * k);
    context.fillStyle = `rgba(216, 216, 222, ${alpha.toFixed(3)})`;
    context.beginPath();
    context.arc(puff.x, puff.y, radius, 0, Math.PI * 2);
    context.fill();
  }

  // листва
  for (const leaf of ambient.leaves) {
    const fade = Math.min(1, leaf.life * 2, (leaf.ttl - leaf.life) * 1.5);
    context.save();
    context.translate(leaf.x, leaf.y);
    context.rotate(leaf.spin);
    context.globalAlpha = 0.85 * fade;
    context.fillStyle = leaf.color;
    context.fillRect(-2.4, -1.3, 4.8, 2.6);
    context.restore();
  }
  context.globalAlpha = 1;

  // птицы и их тени
  for (const bird of ambient.birds) {
    const flap = Math.sin(bird.wing);
    context.fillStyle = "rgba(10, 10, 12, 0.14)";
    context.beginPath();
    context.ellipse(bird.x - 34, bird.y + 68, 11, 4.2, 0, 0, Math.PI * 2);
    context.fill();
    context.strokeStyle = "rgba(24, 22, 20, 0.85)";
    context.lineWidth = 2.6;
    context.beginPath();
    context.moveTo(bird.x - 10, bird.y - 8 * flap);
    context.quadraticCurveTo(bird.x, bird.y + 4 * flap, bird.x + 10, bird.y - 8 * flap);
    context.stroke();
  }
}
