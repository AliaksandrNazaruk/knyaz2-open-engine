// Чтение content pack: JSON, картинки, предзагрузка.
import { statusNode } from "./dom.js";
import { world } from "./world.js";

// ВЕРСИЯ ПАКА В АДРЕСЕ. Имена файлов между сборками не меняются, поэтому
// браузер, однажды положив map.json или лист в кеш, держал их до истечения
// срока — и после выкладки игрок получал СМЕСЬ старого и нового: у нас так
// пропали отряды по мирам, хотя на сервере они уже лежали. Заголовки этого
// не лечат: у сохранённой записи остаётся её прежний срок.
//
// Поэтому к каждому адресу пака приписывается его версия. Меняется пак —
// меняются адреса, и кеш перестаёт совпадать сам собой; не меняется —
// файлы берутся из кеша, как и должны.
let version = "";

export function setContentVersion(value) {
  version = value ? String(value) : "";
}

export function contentUrl(path) {
  const address = `/content/${path.split("/").map(encodeURIComponent).join("/")}`;
  return version ? `${address}?v=${encodeURIComponent(version)}` : address;
}

// ЧИТАЕМ ПО ПРАВИЛАМ КЕША, А НЕ МИМО НЕГО.
//
// Здесь стояло `cache: "no-store"`, и оно било по самому тяжёлому: описание
// карты весит до 3.3 МБ, а `no-store` запрещает браузеру и хранить его, и
// брать сохранённое. Каждый вход на карту — даже возврат туда, где игрок был
// минуту назад, — качал эти мегабайты заново.
//
// Свежесть держится не здесь, а на адресах: в них подставлена свёртка пака
// (`contentUrl`), и любая правка меняет ссылку. Манифест версии не имеет и
// приходит по своему имени, но ему сервер шлёт `no-cache` — браузер
// переспрашивает его каждый раз и получает 304, пока пак не изменился.
export async function readJson(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${path}`);
  return response.json();
}

export function loadImage(path) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`Не удалось загрузить ${path}`));
    image.src = contentUrl(path);
  });
}

export async function preload(paths) {
  // УЖЕ ЗАГРУЖЕННОЕ НЕ ГРУЗИМ ЗАНОВО. Вход на карту зовёт `preload` со всем
  // списком её ресурсов, и при возврате туда, где игрок уже был, каждый файл
  // заводил новый `Image` и раскодировался заново. Сеть за это не платит
  // (адреса версионные, ответ приходит из кэша), а вот раскодирование платит:
  // на карте это шесть сотен картинок за раз.
  const unique = [...new Set(paths.filter(Boolean))]
    .filter((path) => !world.images.has(path)).sort();
  let loaded = 0;
  await Promise.all(unique.map(async (path) => {
    try {
      const image = await loadImage(path);
      world.images.set(path, image);
    } catch (error) {
      world.missingAssets.add(path);
      console.warn(error);
    } finally {
      loaded += 1;
    }
    if (loaded % 20 === 0 || loaded === unique.length) {
      statusNode.textContent = `Ресурсы ${loaded}/${unique.length}`;
      //: Тот же счёт — полосе на экране загрузки (loadscreen.js).
      world.onAssetProgress?.(loaded, unique.length);
    }
  }));
}
