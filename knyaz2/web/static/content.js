// Чтение content pack: JSON, картинки, предзагрузка.
import { statusNode } from "./dom.js";
import { world } from "./world.js";

export function contentUrl(path) {
  return `/content/${path.split("/").map(encodeURIComponent).join("/")}`;
}

export async function readJson(path) {
  const response = await fetch(path, { cache: "no-store" });
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
  const unique = [...new Set(paths.filter(Boolean))].sort();
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
    }
  }));
}
