// Ввод: клавиши героя, перетаскивание камеры, зум, флажки панели.
import { canvas, clockMoonNode, clockRunNode, clockTimeNode, combatStanceNode,
         cursorNode, debugGroundNode, debugObjectsNode, dynamicShadowsNode,
         showRoofsNode } from "./dom.js";
import { clampCamera, screenToWorld, updateZoom, view } from "./viewport.js";
import { daylight, daylightSet } from "./daylight.js";
import { edgeScroll, hero, heroOrderTo, keys } from "./hero.js";
import { orderAt } from "./combat.js";
import { pressButton, refresh as refreshUi } from "./ui.js";
import { selectBand } from "./orders.js";
import { units } from "./units.js";
import { band } from "./viewport.js";
import { updateDebugInfo } from "./debug.js";
import { render } from "./scene.js";
import { cursorApply } from "./cursors.js";

window.addEventListener("keydown", (event) => {
  if (["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown",
       "ArrowLeft", "ArrowRight"].includes(event.code)) {
    keys.add(event.code);
    hero.target = null;
    hero.goal = null;
    hero.path = [];
    hero.running = false;
    event.preventDefault();
  }
});

window.addEventListener("keyup", (event) => keys.delete(event.code));

// Приказ идти: движок различает режимы движения, и режим 1 ставит бит бега
// (VA 0x416641). Одиночный клик — шаг, двойной — бег.
function heroOrderMove(event, running) {
  if (!hero.data) return;
  const point = screenToWorld(event.clientX, event.clientY);
  // Щелчок разбирается по канону движка, а клавиша-добавка решает, менять
  // выбор или дополнять (VA 0x423F80 смотрит флаг 0x849608).
  orderAt(point.x, point.y, running, event.shiftKey);
  // Щелчок мог сменить выбор — а значит и круг под юнитом, и содержимое
  // панели. Без этого выбор менялся молча: новый круг появлялся только
  // со следующим кадром, а панель не обновлялась вовсе.
  refreshUi();
  render();
}

canvas.addEventListener("click", (event) => {
  if (view.dragged) return;                    // перетаскивание камеры — не приказ
  heroOrderMove(event, false);
});

canvas.addEventListener("dblclick", (event) => heroOrderMove(event, true));

// Стойка — бит 0x04 байта unit+0x19. В движке её переключает бой; пока боя
// нет, даём переключатель, чтобы видеть оба набора анимаций.
combatStanceNode.addEventListener("change", () => {
  hero.stance = combatStanceNode.checked ? "combat" : "peace";
  render();
});

clockTimeNode.addEventListener("input", () => {
  clockRunNode.checked = false;
  daylightSet(Number(clockTimeNode.value));
  render();
});

clockMoonNode.addEventListener("change", () => { daylightSet(daylight.time); render(); });

dynamicShadowsNode.addEventListener("change", render);

// ЛЕВАЯ кнопка тянет РАМКУ ВЫБОРА, как в движке (VA 0x42A6E0): протяжка
// ловит живых своих в прямоугольнике. Камера в оригинале водится курсором
// у края экрана; в браузере это неудобно, поэтому её перенесли на СРЕДНЮЮ
// кнопку — это наша замена краевой прокрутки, а не канон.
canvas.addEventListener("pointerdown", (event) => {
  view.pointerX = event.clientX;
  view.pointerY = event.clientY;
  view.dragged = false;
  if (event.button === 0) {
    const point = screenToWorld(event.clientX, event.clientY);
    band.active = true;
    band.addMode = event.shiftKey;
    band.fromX = point.x;
    band.fromY = point.y;
    band.toX = point.x;
    band.toY = point.y;
  } else {
    view.dragging = true;
    canvas.classList.add("dragging");
  }
  canvas.setPointerCapture(event.pointerId);
});

canvas.addEventListener("pointermove", (event) => {
  if (band.active) {
    const point = screenToWorld(event.clientX, event.clientY);
    band.toX = point.x;
    band.toY = point.y;
    if (Math.abs(event.clientX - view.pointerX) + Math.abs(event.clientY - view.pointerY) > 3) {
      view.dragged = true;
    }
    render();
  }
  if (view.dragging) {
    if (Math.abs(event.clientX - view.pointerX) + Math.abs(event.clientY - view.pointerY) > 3) {
      view.dragged = true;
    }
    view.cameraX -= (event.clientX - view.pointerX) / view.zoom;
    view.cameraY -= (event.clientY - view.pointerY) / view.zoom;
    clampCamera();
    view.pointerX = event.clientX;
    view.pointerY = event.clientY;
    render();
  }
  // Прокрутка курсором у края окна — так камеру водит движок
  // (VA 0x437CD0). Запоминаем экранную точку, а двигает камеру такт: в
  // оригинале это тоже делается каждый кадр, пока курсор у края.
  const box = canvas.getBoundingClientRect();
  edge.x = event.clientX - box.left;
  edge.y = event.clientY - box.top;
  edge.width = box.width;
  edge.height = box.height;
  edge.inside = true;
  const point = screenToWorld(event.clientX, event.clientY);
  // Курсор выбирается по тому, что под мышью, — как в движке.
  cursorApply(canvas, point.x, point.y);
  cursorNode.textContent = `Мировая точка: ${Math.round(point.x)}, ${Math.round(point.y)}`;
  updateDebugInfo(point);
});

function endDrag(event) {
  if (band.active) {
    band.active = false;
    // Протяжка длиной меньше трёх пикселей — это щелчок, его разбирает
    // обработчик click; рамкой считаем только настоящее движение.
    if (view.dragged) {
      const box = {
        left: Math.min(band.fromX, band.toX), right: Math.max(band.fromX, band.toX),
        top: Math.min(band.fromY, band.toY), bottom: Math.max(band.fromY, band.toY),
      };
      selectBand([hero, ...units], box, band.addMode);
      refreshUi();
      render();
    }
  }
  view.dragging = false;
  canvas.classList.remove("dragging");
  if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
}

canvas.addEventListener("pointerup", endDrag);

canvas.addEventListener("pointercancel", endDrag);

canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  const before = screenToWorld(event.clientX, event.clientY);
  const rect = canvas.getBoundingClientRect();
  const screenX = event.clientX - rect.left - view.width / 2;
  const screenY = event.clientY - rect.top - view.height / 2;
  view.zoom = Math.max(0.1, Math.min(2.5, view.zoom * Math.exp(-event.deltaY * 0.001)));
  view.cameraX = before.x - screenX / view.zoom;
  view.cameraY = before.y - screenY / view.zoom;
  // Зум меняет видимую половину, поэтому рамку надо пересчитать и здесь:
  // отъехав, камера иначе показала бы пустоту за краем карты.
  clampCamera();
  updateZoom();
  render();
}, { passive: false });

for (const control of [showRoofsNode, debugGroundNode, debugObjectsNode]) {
  control.addEventListener("change", render);
}

window.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() !== "d" || event.repeat) return;
  const enabled = !(debugGroundNode.checked || debugObjectsNode.checked);
  debugGroundNode.checked = enabled;
  debugObjectsNode.checked = enabled;
  render();
});


// Клавиши панели — те же, что в оригинале: подсказки движка называют их
// «Все ко мне (F)», «Карта (M)», «Достать/Убрать оружие (Пробел)»,
// «Атаковать (A)», «Информация к размышлению (Q)», «Панель персонажа (I)».
const PANEL_KEYS = {
  KeyF: "call_party", KeyM: "map", Space: "toggle_weapon",
  KeyA: "attack", KeyQ: "journal", KeyI: "character",
};

window.addEventListener("keydown", (event) => {
  const action = PANEL_KEYS[event.code];
  if (!action || event.repeat) return;
  event.preventDefault();
  pressButton(action);
});

//: Где сейчас курсор в окне — по нему камера ползёт у края (VA 0x437CD0).
export const edge = { x: 0, y: 0, width: 0, height: 0, inside: false };

// Такт прокрутки: пока курсор у самого края, камера едет. Зовётся из
// главного цикла, как и в движке.
export function edgeScrollTick() {
  if (!edge.inside || view.dragging || band.active) return false;
  return edgeScroll(edge.x, edge.y, edge.width, edge.height);
}

canvas.addEventListener("pointerleave", () => { edge.inside = false; });
