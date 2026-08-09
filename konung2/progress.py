# -*- coding: utf-8 -*-
"""
Опыт, уровни и прокачка — правила движка.

Всё снято с кода, ничего не выдумано:

* опыт копится в ``unit+0x22``, порог следующего уровня лежит в ``unit+0x2A``,
  уровень — байт ``unit+0xF3`` (VA 0x413142);
* порог уровня N — сумма ``i * 100`` для i от 1 до N, то есть 100·N·(N+1)/2
  (VA 0x41AA34): 100, 300, 600, 1000, 1500…;
* за уровень дают 25 «свободного опыта» в ``unit+0x48`` (VA 0x413157), и
  именно он тратится на характеристики и навыки;
* опыт за убитого — взвешенная сумма его же характеристик, навыков и брони
  (VA 0x41B044), а начисляется убийце его четверть (VA 0x414150).

Панель персонажа показывает шесть характеристик и двадцать навыков
(VA 0x42B672 и 0x42B7BD):

    базовая характеристика   unit+0xC0 + i     текущая  unit+0xCC + i
    навык                    unit+0xD2 + i

Поднять характеристику стоит 2 свободного опыта, потолок 150, и проверяется
**базовое** значение ``unit+0xC0+i``, а не текущее (VA 0x4131FC).
Поднять навык стоит 1, но только пока он меньше предела из таблицы
``SKILL_LIMITS`` и не больше 100 (VA 0x413268).

Обе прокачки заперты полем ``unit+0x4A``: пока оно не ноль, ничего поднять
нельзя (VA 0x4131FC и 0x413268, первая же проверка).
"""
from __future__ import annotations

#: Начисление и уровни.
XP_FIELD, XP_NEXT_FIELD, LEVEL_FIELD, FREE_XP_FIELD = 0x22, 0x2A, 0xF3, 0x48
FREE_XP_PER_LEVEL = 25
KILL_XP_SHARE = 4               # убийце достаётся четверть (VA 0x414150)
#: Замок прокачки: пока unit+0x4A != 0, ни характеристика, ни навык не растут.
LOCK_FIELD = 0x4A

#: Множитель начисления (VA 0x413110): опыт не больше 2000 умножается на
#: ``настройка + 2``, где настройка — первое поле KONUNG2.CFG (VA 0x84958C,
#: читается в 0x42EBD0). Без файла настроек движок ставит 0.
XP_MULTIPLIER_LIMIT = 2000
#: Дефолт движка при отсутствии KONUNG2.CFG (VA 0x42EBD0, ветка -1).
XP_MULTIPLIER_DEFAULT = 0


def xp_multiplier_setting() -> int:
    """Настройка множителя опыта — первое dword KONUNG2.CFG.

    Это не константа движка, а настройка меню (0x438A00, cases 10/11/12
    пишут 2/1/0): загрузчик 0x42EBD0 читает её первым полем файла, а без
    файла ставит 0. Читаем из той же установки игры, что и остальные данные.
    """
    from .paths import game_file
    try:
        with open(game_file("KONUNG2.CFG"), "rb") as stream:
            raw = stream.read(4)
    except OSError:
        return XP_MULTIPLIER_DEFAULT
    if len(raw) < 4:
        return XP_MULTIPLIER_DEFAULT
    return int.from_bytes(raw, "little", signed=True)
#: Веса опыта за убитого зверя — флаг ``unit+0x1A & 0x40``
#: (VA 0x41B059…0x41B0C8, константы 0x4500AC=0.2, 0x4500B4=0.3, 0x4500BC=0.1).
KILL_XP_WEIGHTS = {"parry": 0.2, "strength": 0.3, "endurance": 0.3, "armour": 0.1}
#: Веса опыта за убитого человека — тот же флаг снят
#: (VA 0x41B0CD…0x41B185, константы 0x4500C4=0.2, 0x4500CC=0.3,
#: 0x4500D4=1.2, 0x4500DC=1.8, 0x4500E4=0.1). Отличие от зверя — два
#: навыковых слагаемых: владение оружием ближнего боя и метательным.
KILL_XP_WEIGHTS_HUMAN = {
    "parry": 0.2, "strength": 0.3, "endurance": 0.3,
    "melee_skill": 1.2, "ranged_skill": 1.8, "armour": 0.1,
}
#: Надбавка за оружие в руке (VA 0x41B188…0x41B202, константа 0x4500EC=0.2):
#: когда режим стрельбы снят (байт +0xEE == 0) и ОСНОВНАЯ РУКА занята
#: (слот +0x58 + режим·2, при нулевом режиме это она), к опыту добавляется
#: доля защиты класса предмета руки отдельным округлением.
KILL_XP_WEAPON_WEIGHT = 0.2
#: Флаг «зверь» в unit+0x1A (VA 0x41B053).
BEAST_FLAG_AT, BEAST_FLAG = 0x1A, 0x40

#: Характеристики: имя из exe, базовая по +0xC0+i, текущая по +0xCC+i.
CHARACTERISTICS = ("Харизма", "Ловкость", "Интеллект", "Обучаемость",
                   "Сила", "Выносливость")
BASE_AT, CURRENT_AT = 0xC0, 0xCC
CHARACTERISTIC_COST = 2
CHARACTERISTIC_CAP = 150

#: Навыки: имя из exe, индекс = смещение от unit+0xD2.
SKILLS = (
    "Рукопашный бой", "Бой двумя руками", "Смертельный удар",
    "Владение мечом", "Владение топором", "Владение дубиной",
    "Владение двуручным мечом", "Владение двуручным топором",
    "Владение двуручной дубиной", "Стрельба из арбалета", "Стрельба из лука",
    "Знахарство", "Приготовление смесей", "Следопыт", "Торговля",
    "Идентификация предметов", "Волхование", "Кузнечное дело",
    "Строительные навыки", "Управление деревней",
)
SKILLS_AT = 0xD2
SKILL_COST = 1
SKILL_CAP = 100
LEARNING_INDEX = 3              # Обучаемость: её четверть входит в предел
LEARNING_DIVISOR = 4

#: Предел роста навыка (VA 0x413268) — switch по номеру навыка. Основа у всех
#: одна: ``Обучаемость >> 2``. Дальше три разных вида выражения:
#:
#:     avg    основа + среднее перечисленных характеристик
#:     half   (сумма характеристик + основа) / 2      — только «Смертельный удар»
#:     double (сумма характеристик + основа) * 2      — «умственные» навыки
#:
#: Все деления целочисленные, итог зажат сотней. Индексы характеристик:
#: 0 Харизма (+0xCC), 1 Ловкость (+0xCD), 2 Интеллект (+0xCE),
#: 3 Обучаемость (+0xCF), 4 Сила (+0xD0), 5 Выносливость (+0xD1).
#:
#: ``prereq`` — условие допуска: пока ни один из перечисленных навыков не
#: дорос до порога, движок отказывает вовсе (``return 0`` до расчёта предела).
SKILL_LIMITS = (
    {"kind": "avg", "chars": (4, 1)},                        # 0  Рукопашный бой
    {"kind": "avg", "chars": (4, 1),                         # 1  Бой двумя руками
     "prereq": {"skills": (0, 4, 5, 3), "threshold": 25}},
    {"kind": "half", "chars": (1,),                          # 2  Смертельный удар
     "prereq": {"skills": (9, 0, 4, 7, 10, 5, 8, 3, 6), "threshold": 50}},
    {"kind": "avg", "chars": (4, 1)},                        # 3  Владение мечом
    {"kind": "avg", "chars": (4, 5)},                        # 4  Владение топором
    {"kind": "avg", "chars": (4, 5)},                        # 5  Владение дубиной
    {"kind": "avg", "chars": (1, 5, 4)},                     # 6  Двуручный меч
    {"kind": "avg", "chars": (1, 5, 4)},                     # 7  Двуручный топор
    {"kind": "avg", "chars": (1, 5, 4)},                     # 8  Двуручная дубина
    {"kind": "avg", "chars": (1,)},                          # 9  Арбалет
    {"kind": "avg", "chars": (4, 1)},                        # 10 Лук
    {"kind": "double", "chars": (2,)},                       # 11 Знахарство
    {"kind": "double", "chars": (2,)},                       # 12 Приготовление смесей
    {"kind": "avg", "chars": (2, 5)},                        # 13 Следопыт
    {"kind": "avg", "chars": (2, 0)},                        # 14 Торговля
    {"kind": "double", "chars": (2,)},                       # 15 Идентификация
    {"kind": "double", "chars": (2,)},                       # 16 Волхование
    {"kind": "avg", "chars": (1, 2, 4)},                     # 17 Кузнечное дело
    {"kind": "avg", "chars": (2, 4)},                        # 18 Строительные навыки
    {"kind": "avg", "chars": (2, 0)},                        # 19 Управление деревней
)


def level_threshold(level: int) -> int:
    """Сколько всего опыта нужно на уровень N (VA 0x41AA34)."""
    return sum(i * 100 for i in range(1, max(0, level) + 1))


def kill_experience(parry: int, strength: int, endurance: int, armour: int,
                    *, beast: bool = True, melee_skill: int = 0,
                    ranged_skill: int = 0, weapon_armour: int = 0) -> int:
    """Опыт за убитого юнита (VA 0x41B044).

    У зверей (``unit+0x1A & 0x40``) считаются только характеристики и броня,
    у людей к ним добавляются владение оружием ближнего боя и метательным.
    ``weapon_armour`` — защита класса предмета основной руки, идёт надбавкой
    отдельным округлением (VA 0x41B188); передавать её нужно только когда у
    юнита снят режим стрельбы (байт +0xEE == 0) и рука занята (+0x58).
    """
    weights = KILL_XP_WEIGHTS if beast else KILL_XP_WEIGHTS_HUMAN
    total = (parry * weights["parry"] +
             strength * weights["strength"] +
             endurance * weights["endurance"])
    if not beast:
        total += (melee_skill * weights["melee_skill"] +
                  ranged_skill * weights["ranged_skill"])
    total += armour * weights["armour"]
    value = round_half_even(total)
    if weapon_armour:
        value = round_half_even(weapon_armour * KILL_XP_WEAPON_WEIGHT + value)
    return value


def round_half_even(value: float) -> int:
    """Округление сопроцессора (``fistp``): к ближайшему, при половине — к чётному."""
    return int(round(value))


def kill_share(experience: int) -> int:
    """Доля убийцы — четверть с усечением к нулю, без нижней границы (VA 0x414150)."""
    return int(experience / KILL_XP_SHARE)


def gain_experience(experience: int, setting: int | None = None) -> int:
    """Сколько опыта реально ляжет в ``unit+0x22`` (VA 0x413110)."""
    if setting is None:
        setting = xp_multiplier_setting()
    if experience <= XP_MULTIPLIER_LIMIT:
        return experience * (setting + 2)
    return experience


def skill_limit(skill_index: int, characteristics, skills) -> int:
    """Предел роста навыка (VA 0x413268).

    Возвращает 0, если навык вообще нельзя поднимать: не выполнено условие
    допуска (``prereq``) — движок в этом случае выходит до расчёта.
    """
    rule = SKILL_LIMITS[skill_index]
    prereq = rule.get("prereq")
    if prereq and all(skills[i] < prereq["threshold"] for i in prereq["skills"]):
        return 0
    base = characteristics[LEARNING_INDEX] // LEARNING_DIVISOR
    total = sum(characteristics[i] for i in rule["chars"])
    if rule["kind"] == "avg":
        limit = base + total // len(rule["chars"])
    elif rule["kind"] == "half":
        limit = (total + base) // 2
    else:                                   # double
        limit = (total + base) * 2
    return min(limit, SKILL_CAP)


def rules() -> dict:
    """Правила прокачки одним куском — для content pack."""
    return {
        "policy": "konung2_exe_0x41AA34_0x413268_0x4131FC_0x413110_0x41B044",
        "free_xp_per_level": FREE_XP_PER_LEVEL,
        "kill_xp_share": KILL_XP_SHARE,
        "kill_xp_weights": dict(KILL_XP_WEIGHTS),
        "kill_xp_weights_human": dict(KILL_XP_WEIGHTS_HUMAN),
        "kill_xp_weapon_weight": KILL_XP_WEAPON_WEIGHT,
        "beast_flag": {"at": BEAST_FLAG_AT, "mask": BEAST_FLAG},
        "xp_multiplier": {"at_most": XP_MULTIPLIER_LIMIT,
                          "setting": xp_multiplier_setting()},
        "lock_field": LOCK_FIELD,
        "level_thresholds": [level_threshold(n) for n in range(1, 31)],
        "characteristics": {
            "names": list(CHARACTERISTICS),
            "base_at": BASE_AT, "current_at": CURRENT_AT,
            "cost": CHARACTERISTIC_COST, "cap": CHARACTERISTIC_CAP,
        },
        "skills": {
            "names": list(SKILLS),
            "limits": [dict(rule) for rule in SKILL_LIMITS],
            "at": SKILLS_AT, "cost": SKILL_COST, "cap": SKILL_CAP,
            "learning": {"index": LEARNING_INDEX, "divisor": LEARNING_DIVISOR},
        },
    }
