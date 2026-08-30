// Мерная выжимка входа на карту. Вставляется в консоль браузера целиком.
//
// Зачем отдельным файлом, а не в игре: это инструмент отладки, ему нечего
// делать в том коде, который едет игроку. В `app.js` живёт только подъём
// буфера `performance` — без него браузер выбрасывает всё сверх 250 записей,
// и любой подсчёт трафика врёт в меньшую сторону.
//
// Возвращает JSON: куда ушли байты по категориям пака, чем отдавалось
// (h1/h2/h3), сколько земли доехало и где камера относительно героя.
(async () => {
  const [w, h, vp] = await Promise.all([
    import('/world.js'), import('/hero.js'), import('/viewport.js'),
  ]);
  const записи = performance.getEntriesByType('resource');
  const байт = (e) => e.transferSize || e.encodedBodySize || 0;

  const КАТЕГОРИИ = [
    ['листы актёров', /\/assets\/units\//],
    ['листы тварей', /\/assets\/creatures\//],
    ['земля', /\/assets\/ground\//],
    ['постройки', /\/assets\/objects\//],
    ['оверлеи', /\/assets\/terrain_overlays\//],
    ['свет', /\/assets\/light\//],
    ['звук', /\/assets\/audio\//],
    ['описания', /\.json/],
    ['клиент', /\.(js|css|html)$/],
  ];
  const свод = {};
  let прочее = { шт: 0, МБ: 0 };
  for (const e of записи) {
    const пара = КАТЕГОРИИ.find(([, маска]) => маска.test(e.name));
    const ключ = пара ? пара[0] : null;
    const цель = ключ ? (свод[ключ] ??= { шт: 0, МБ: 0, мс: 0 }) : прочее;
    цель.шт += 1;
    цель.МБ += байт(e) / 1048576;
    if (цель.мс !== undefined) цель.мс = Math.max(цель.мс, Math.round(e.duration));
  }
  for (const к of Object.values(свод)) к.МБ = +к.МБ.toFixed(2);
  прочее.МБ = +прочее.МБ.toFixed(2);

  const протоколы = {};
  for (const e of записи) протоколы[e.nextHopProtocol || '?'] =
    (протоколы[e.nextHopProtocol || '?'] || 0) + 1;

  const земля = [...new Set((w.world.ground ?? []).map((c) => c.asset).filter(Boolean))];
  const листы = (w.world.map?.hero?.sheets ?? []).map((s) => s.path);

  return JSON.stringify({
    карта: `${w.world.map?.legacy?.map_number} ${w.world.map?.name ?? ''}`.trim(),
    буфер_переполнен: записи.length >= (5000 - 1),
    запросов: записи.length,
    всего_МБ: +(записи.reduce((s, e) => s + байт(e), 0) / 1048576).toFixed(2),
    по_категориям: свод,
    прочее,
    протоколы,
    земли_готово: `${земля.filter((p) => w.world.images?.has(p)).length}/${земля.length}`,
    листов_готово: `${листы.filter((p) => w.world.images?.has(p)).length}/${листы.length}`,
    картинок_в_памяти: w.world.images?.size,
    камера_на_герое: Math.abs(vp.view.cameraX - h.hero.x) < 800 &&
                     Math.abs(vp.view.cameraY - h.hero.y) < 800,
    секунд_с_открытия: +(performance.now() / 1000).toFixed(1),
  }, null, 1);
})()
