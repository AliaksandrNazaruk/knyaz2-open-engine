// МИРОВОЙ ТАКТ ДВИЖКА — один счётчик на всю игру.
//
// В движке это `_DAT_0084962c`: он увеличивается на единицу в начале главного
// цикла (VA 0x438A00, строка `_DAT_0084962c = _DAT_0084962c + 1`), и от него
// фазируется ВСЁ периодическое — счётчик работы жителя `& 0xF`, фаза построек
// `+7 & 0xF`, отрава, тренировка поселений, отряды. Отдельных часов у подсистем
// в движке нет.
//
// ЧАСТОТА ДОКАЗАНА ПО МАШИННОМУ КОДУ, а не взята из головы:
//   VA 0x42F1EF  cmp eax, 0x4E / jl  — оконный цикл пропускает такт, пока с
//                прошлого не прошло 78 мс (`eax = timeGetTime() - последний`);
//   VA 0x42F200  push 0x400 → SendMessageA — шлёт WM_USER главному окну;
//   VA 0x42F913  call 0x438A00 — обработчик этого сообщения зовёт главный цикл.
// Скан всей секции кода: `call 0x438A00` встречается РОВНО ОДИН РАЗ (0x42F913),
// поэтому других источников такта нет и период равен ровно 78 мс.
//
// Прежние 1/18 с (55.6 мс) держались на комментарии «~18 тиков/с» и гнали
// игру на 40% быстрее оригинала.
import { world } from "./world.js";

export const TICK_SECONDS = 0.078;

export function tickSeconds() {
  const packed = world.map?.hero?.frame_seconds;
  return packed > 0 ? packed : TICK_SECONDS;
}

export const clock = {
  ticks: 0,        // аналог _DAT_0084962c
  seconds: 0,      // время, до которого счётчик уже досчитан
  elapsed: 0,      // сколько тактов прошло за ЭТОТ кадр браузера
  first: 1,        // номер первого из них
};

// Больше этого числа тактов за один кадр браузера не отдаём. В движке такой
// проблемы нет: там кадр И ЕСТЬ такт, а SendMessageA синхронный. В браузере
// вкладка может уснуть, и без потолка накопленный долг прокрутился бы разом.
const CATCHUP_LIMIT = 4;

export function clockReset(seconds = 0) {
  clock.ticks = 0;
  clock.seconds = seconds;
  clock.elapsed = 0;
  clock.first = 1;
}

// Сколько мировых тактов прошло к этому моменту. Вызывать РОВНО ОДИН РАЗ за
// кадр: счётчик двигается здесь и больше нигде.
export function clockAdvance(seconds) {
  const step = tickSeconds();
  clock.first = clock.ticks + 1;
  clock.elapsed = 0;
  if (!clock.seconds || seconds - clock.seconds > 1) {
    clock.seconds = seconds;
    return 0;
  }
  while (seconds - clock.seconds >= step && clock.elapsed < CATCHUP_LIMIT) {
    clock.seconds += step;
    clock.ticks += 1;
    clock.elapsed += 1;
  }
  return clock.elapsed;
}

// Сколько раз за ЭТОТ кадр сошлась фаза движка `(такт + offset & mask) == 0`.
// Стройка и мастерская идут по `+7 & 0xF` (VA 0x41C944:356), счётчик работы
// жителя — по `& 0xF` (VA 0x413894:72), отряды — раз в 16 тактов.
//
// Считать надо именно попадания, а не проверять текущий такт: кадр браузера
// длиннее такта, за один кадр их проходит несколько, и проверка «сошлась ли
// фаза сейчас» пропускала бы такты при догоне, а при стоящем счётчике,
// наоборот, срабатывала бы каждый кадр подряд.
export function clockPhaseHits(mask = 0xF, offset = 0) {
  let hits = 0;
  for (let i = 0; i < clock.elapsed; i += 1) {
    if (((clock.first + i + offset) & mask) === 0) hits += 1;
  }
  return hits;
}
