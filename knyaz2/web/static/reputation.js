// Репутация — счёт добрых и злых дел «Продолжения легенды».
//
// В КАНОНЕ ЕЁ НЕТ ВОВСЕ: строка «Репутация» есть только в exe донора, и
// рисует её его экран героя (VA 0x00433C30) следующей строкой после
// «Уровень». Разговоры донора двигают счёт обработчиком 49 и спрашивают
// о нём обработчиком 8 — у нас это 177 и 136 в dialog.js, и они давно
// работают: 399 прибавлений и 264 проверки по всему паку.
//
// А ВОТ ВТОРОЙ ИСТОЧНИК СЧЁТА НЕ БЫЛ ПЕРЕНЕСЁН — убийство. Разбор
// правил и все числа лежат в konung2/reputation.py; здесь только их
// применение (VA 0x00418554):
//
//     убийца нашей стороны  +  у жертвы ЕСТЬ разговор   -> цена по таблице
//     убийца нашей стороны  +  разговора нет, тело 15   -> счёт СТАНОВИТСЯ −140
//     убийца нашей стороны  +  разговора нет, тело 14   -> счёт уменьшается на 70
//
// Тела 15 и 14 — не звери: пятнадцатое носят знатные мужи, четырнадцатое
// женщины. То есть вторая и третья строки наказывают за убийство
// БЕЗЫМЯННОГО знатного и безымянной женщины, и цены согласуются с
// таблицей: у именованного князя −120, у безымянного −140.
//
// ЦЕНА ИЩЕТСЯ ПО ПАРЕ «ИГРА + НОМЕР». Номера разговоров обеих игр лежат
// вперемешку (6…151 у канона, 6…145 у донора), и один номер значит в них
// разных людей. Канонной жертве цены нет вовсе: в её игре механики не
// существует.
//: ГЕРОЙ ПРИХОДИТ ДОВОДОМ, А НЕ ИМПОРТОМ. Правило не должно знать про
//: глобального игрока: `hero.js` тянет за собой DOM, и модуль правил
//: становилось нечем проверить вне браузера. Теперь он грузится в node
//: и проверяется на выдуманных юнитах (tests/test_reputation_contract.py).
import { shared } from "./world.js";

//: Породы 84…86 несут бит 0x40; движок им и проверяет вторую ветвь.
const BREED_MARK = 0x40;
const NO_TALK = 0xFF;

function rules() {
  return shared.reputation ?? null;
}

export function reputationValue(player) {
  return player?.reputation ?? 0;
}

//: Цена убийства именованного. Ключи в паке строками — JSON других не знает.
//: Наружу не отдаём: за пределами правила цена сама по себе не нужна, а
//: лишний экспорт — это приглашение завести вторую реализацию.
function killCost(unit) {
  const table = rules()?.kill_costs;
  if (!table || unit?.game !== "legend") return 0;
  const number = unit?.dialogNumber;
  if (typeof number !== "number" || number === NO_TALK) return 0;
  return Number(table[String(number)] ?? 0);
}

// Правило VA 0x00418554 целиком. Возвращает, изменился ли счёт, — не для
// логики, а чтобы вызывающий мог сказать об этом игроку.
export function reputationKill(attacker, defender, player) {
  if (!attacker || !defender || !player) return false;
  //: «Убил кто-то из наших» — байт +0x1B у убийцы совпал с игроковым.
  //: Признак `ally` стоит рядом не для красоты: спутник заводится с
  //: `side: hero.side ?? 0`, но у приёмышей и нанятых сторона успевает
  //: смениться, и весь клиент проверяет эту пару вместе (cursors.js,
  //: units.js, dialog.js). Держимся той же идиомы.
  if (!(attacker.ally || attacker === player
        || (attacker.side ?? 0) === (player.side ?? 0))) return false;
  const before = reputationValue(player);
  const number = defender.dialogNumber;
  const named = typeof number === "number" && number !== NO_TALK;
  if (named) {
    player.reputation = before + killCost(defender);
  } else if (((defender.breed ?? 0) & BREED_MARK) !== 0) {
    const marks = rules()?.nameless;
    if (!marks) return false;
    const body = defender.body ?? 0;
    //: ПРИСВАИВАНИЕ, А НЕ ВЫЧИТАНИЕ. У знатного движок пишет `= -0x8c`:
    //: сколько бы ни было накоплено, убийство безымянного князя роняет
    //: счёт на дно. У женщины — обычная убавка.
    if (body === marks.noble_body) player.reputation = marks.noble_set;
    else if (body === marks.woman_body) player.reputation = before + marks.woman_add;
  }
  return reputationValue(player) !== before;
}

// Новая игра: счёт начинается не с нуля. У четырёх героев донора он свой
// (таблица 0x465A28), у канонных нулевой — механики в их игре нет.
export function reputationStart(player, start) {
  player.reputation = Number(start?.reputation ?? 0);
}
