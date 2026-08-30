// Узлы страницы в одном месте: остальные модули не ищут их сами.
export const canvas = document.querySelector("#world");

//: СТРОКА СОСТОЯНИЯ ЖИВЁТ В ИГРЕ, А НЕ В ОТЛАДОЧНОЙ ПАНЕЛИ. Прежде это был
//: `#status` из боковой панели, а панель сняли с экрана стилями — и все
//: двадцать четыре места, которые сюда пишут, стали писать в невидимое:
//: имя врага под курсором, «Засада!», «Дальше пути нет», «карты нет в паке».
//: Теперь берём полосу внизу игрового окна, а `#status` остаётся запасным —
//: он всё ещё нужен странице отладки (?debug=1) и тестам.
export const statusNode = document.querySelector("#ui-status")
  ?? document.querySelector("#status");

// СООБЩЕНИЕ ГАСНЕТ САМО. Пока строка лежала в скрытой отладочной панели, её
// никто не чистил — и это не мешало. На экране игры мешает: «Засада!» с
// прошлого боя висела над поясом до конца сеанса, и её принимали за подпись
// инвентаря. Все двадцать с лишним сообщений событийные («Поднято», «Брошено»,
// «Заперто», «Переход»), им положено гаснуть.
//
// Сторожим сам узел, а не правим два десятка мест записи: каждая новая запись
// продлевает срок. Заодно это верно для прогресса загрузки — он обновляется
// часто, поэтому виден всё время загрузки и гаснет вскоре после её конца.
//
//: СРОК — НАШ, не из движка. У движка своя табличка с жизнью в двенадцать
//: мировых тактов (0x84972C), но это подпись под курсором, и она у нас теперь
//: живёт отдельным узлом у самой мыши. Здесь же наши сообщения, и шесть
//: секунд взяты как время спокойно прочесть строку.
const STATUS_LIFE = 6000;

if (statusNode && statusNode.id === "ui-status") {
  let deadline = 0;
  new MutationObserver(() => {
    clearTimeout(deadline);
    if (!statusNode.textContent) return;
    deadline = setTimeout(() => { statusNode.textContent = ""; }, STATUS_LIFE);
  }).observe(statusNode, { childList: true, characterData: true, subtree: true });
}

export const zoomNode = document.querySelector("#zoom");

export const titleNode = document.querySelector("#map-title");

export const statsNode = document.querySelector("#stats");

export const cursorNode = document.querySelector("#cursor");

export const errorNode = document.querySelector("#error");

export const combatStanceNode = document.querySelector("#combat-stance");
export const showRoofsNode = document.querySelector("#show-roofs");

export const debugGroundNode = document.querySelector("#debug-ground");

export const debugObjectsNode = document.querySelector("#debug-objects");

export const debugInfoNode = document.querySelector("#debug-info");

export const audioTrackNode = document.querySelector("#audio-track");

export const audioToggleNode = document.querySelector("#audio-toggle");

export const clockRunNode = document.querySelector("#clock-run");

export const clockMoonNode = document.querySelector("#clock-moon");

export const dynamicShadowsNode = document.querySelector("#dynamic-shadows");

export const clockTimeNode = document.querySelector("#clock-time");

export const clockLabelNode = document.querySelector("#clock-label");

export const ambientNode = document.querySelector("#ambient-fx");
