"""Первая игра серии: разбор карт «Князя» (konung2/konung1.py)."""
from __future__ import annotations

import unittest

from konung2 import konung1


class Konung1Test(unittest.TestCase):
    """Что установлено по «Легендам лесной страны»."""

    def setUp(self) -> None:
        if not konung1.available():
            self.skipTest("первой игры нет рядом")

    def test_location_names_are_a_flat_table(self) -> None:
        """Имена лежат ПОДРЯД, а не таблицей указателей.

        У «Князя 2» это массив указателей на строки, и первый заход я
        искала здесь то же самое — указателей на «Черный Бор» в exe нет
        ни одного. Записи оказались фиксированными, по 40 байт со
        смещения 275956.
        """
        names = konung1.location_names()
        self.assertEqual(len(names), 50)
        self.assertEqual(names[18], "Черный Бор")
        self.assertEqual(names[32], "Борье")
        #: номер файла карты на единицу больше номера локации
        self.assertEqual(konung1.map_name(19), "Черный Бор")
        self.assertEqual(konung1.map_name(33), "Борье")

    def test_seven_maps_are_named_but_missing(self) -> None:
        """Своё невключённое содержимое: имя есть, файла нет.

        Семь локаций названы, а карт под них не существует — «Болото у
        Византийского Лагеря», «Поляны у Ловье», «Пепелище у Лесовья»,
        «Островок на болоте», «Пещера у Камней», «Рудник у Борья»,
        «Гнездо».
        """
        numbers = konung1.map_numbers()
        self.assertEqual(len(numbers), 43)
        пропуски = [н for н in range(1, 51) if н not in numbers]
        self.assertEqual(пропуски, [9, 13, 18, 26, 31, 34, 41])
        names = konung1.location_names()
        self.assertEqual(names[12], "Поляны у Ловье")
        self.assertEqual(names[33], "Рудник у Борья")

    def test_ground_grid_matches_the_sequel(self) -> None:
        """Слой земли тот же, что у «Князя 2»: 160 рядов на 80 столбцов.

        Проверено рисунком: при 80x160 картинка распадалась надвое, при
        160x80 сложилась в связный ландшафт с водой и дорогами.
        """
        cells = konung1.ground(19)
        self.assertEqual(len(cells), 160)
        self.assertEqual(len(cells[0]), 80)
        #: карта лежит в УГЛУ сетки, а не занимает её целиком
        rows_count, cols_count = konung1._ground_extent(cells)
        self.assertLess(cols_count, 80)

    def test_cell_is_two_tiles_not_one_number(self) -> None:
        """В клетке ПАРА плиток — нижняя и верхняя, как во второй игре.

        Сперва я читала клетку как u16 и получала номера до 33924 при
        таблице в 305 плиток — верный признак, что число составное.
        0x8484 оказалось плиткой 132 в обоих слоях.
        """
        cells = konung1.ground(22)
        for line in cells:
            for низ, верх in line:
                self.assertLess(низ, 256)
                self.assertLess(верх, 256)
        пары = {pair for line in cells for pair in line if any(pair)}
        #: слоёв два и они разные: у Поречья 14 нижних и 32 верхних
        self.assertGreater(len({н for н, _ in пары}), 5)
        self.assertGreater(len({в for _, в in пары}), 5)

    def test_map_holds_two_tables_not_one(self) -> None:
        """Декорации и объекты — РАЗНЫЕ таблицы, и я их перепутала.

        Таблицу на 0x12C00 я приняла за таблицу объектов, читала её
        номер плитки как номер спрайта и рисовала им постройки. Выходило
        связно и потому убедительно: дома вставали там, где на деле
        лежит трава, а настоящих домов на карте не было вовсе.

        Раскладка взята из открытого движка (Slavik, LoadGameMap) и
        проверяется тем, что четыре слоя дают длину файла БЕЗ ОСТАТКА:
        25600 земли, 51200 проходимости, 16000 декораций, 36000
        объектов — ровно 128800.
        """
        self.assertEqual(konung1.DECORATIONS_AT, 0x12C00)
        self.assertEqual(konung1.OBJECTS_AT, 0x16A80)
        self.assertEqual(konung1.OBJECT_STRIDE, 36)
        всего = (konung1.GROUND_SIZE + konung1.FOOT_SIZE
                 + konung1.MAP_TABLE_SLOTS * konung1.DECORATION_STRIDE
                 + konung1.MAP_TABLE_SLOTS * konung1.OBJECT_STRIDE)
        self.assertEqual(всего, 128800)
        for number in konung1.map_numbers():
            size = konung1.game_file(f"KONUNG.{number}").stat().st_size
            self.assertEqual(size, всего, f"карта {number}: длина не та")
        #: в деревне есть и то, и другое
        self.assertEqual(len(konung1.decorations(22)), 154)
        self.assertEqual(len(konung1.objects(22)), 205)

    def test_object_coordinates_are_half_cells(self) -> None:
        """Место объекта хранится в ПОЛУКЛЕТКАХ, а не в точках.

        Перевод из движка: ``x = столбец * 116 / 2 - (ряд & 1) * 29``,
        ``y = ряд * 64 / 4``. Сетка вдвое мельче плиточной — как и слой
        проходимости 160 x 320 против земли 80 x 160. Без перевода вся
        деревня сбивается в левый верхний угол карты.
        """
        for number in (22, 19, 33):
            cells = konung1.ground(number)
            rows_count, cols_count = konung1._ground_extent(cells)
            for о in konung1.objects(number):
                self.assertLessEqual(о["col"], cols_count * 2 + 2)
                self.assertLessEqual(о["row"], rows_count * 2 + 2)
                self.assertLessEqual(о["y"], rows_count * konung1.TILE_H)


class Konung1GraphicsTest(unittest.TestCase):
    """Графика первой игры: контейнеры, плитки и спрайты объектов."""

    def setUp(self) -> None:
        if not konung1.available():
            self.skipTest("первой игры нет рядом")

    def test_tables_hold_512_slots_not_1000(self) -> None:
        """Вся разница контейнеров — в длине таблицы.

        Я трижды объявляла формат «другим» и переделанным целиком. На
        деле кодек и палитры у обеих игр общие (он и снят с открытой
        реимплементации первой части), а таблиц две и обе на 512 гнёзд
        вместо 1000. Из-за этого я брала данные плиток на 0x23178 —
        то есть сразу за 305 живыми записями — и читала шум, который
        приняла за траву.
        """
        self.assertEqual(konung1.SLOTS, 512)
        self.assertEqual(konung1.TILE_DATA_AT, konung1.TILE_TABLE_AT + 0x1000)
        гр = konung1.Graph.from_game()
        tile = гр.tile(5)
        self.assertIsNotNone(tile, "плитка не разобралась — база не та")
        #: тот же размер плитки, что у «Крови Титанов»
        self.assertEqual((tile.width, tile.height), (114, 64))

    def test_object_records_chain_to_the_end_of_the_file(self) -> None:
        """Смещения записей считаются от КОНЦА таблицы (4104).

        Это и есть проверка контейнера: при верном сдвиге конец
        последней записи совпадает с длиной файла байт в байт, а все
        стыки сходятся. При сдвиге 0 или 8 хвост уезжает на 4104 и 4096.
        """
        data = konung1.game_file("OBJECTS.RES").read_bytes()
        об = konung1.Objects(data)
        живые = [г for г in об.nests if г]
        self.assertEqual(len(живые), 493)
        begin, length = живые[-1]
        self.assertEqual(begin + length, len(data))
        for (о, р), (о2, _) in zip(живые, живые[1:]):
            self.assertEqual(о + р, о2, "записи должны лежать подряд")

    def test_record_header_is_the_sequel_shifted_by_four(self) -> None:
        """Заголовок тот же, что у «Крови Титанов», но сдвинут на 4 байта.

        Признак, по которому он опознан: на +0x04 лежит длина всей
        записи, и она совпадает с длиной гнезда у каждого живого слота.
        """
        об = konung1.Objects.from_game()
        проверено = 0
        for slot in range(konung1.SLOTS):
            head = об.header(slot)
            if head is None:
                continue
            self.assertEqual(head["size"], head["length"],
                             f"слот {slot}: длина в заголовке не та")
            проверено += 1
        self.assertGreater(проверено, 450)

    def test_simple_object_slot_is_id_plus_thirty(self) -> None:
        """Гнездо простого объекта — это его номер ПЛЮС ТРИДЦАТЬ.

        Первые тридцать гнёзд OBJECTS.RES отданы динамическим объектам:
        у открытого движка это ровно ``std::array<DynamicObject, 30>`` и
        ``std::array<SimpleObject, 482>``, вместе 512. Сперва я решила,
        что номер равен гнезду как есть, — потому что подбирала базу по
        «правдоподобию размеров», а не по коду.
        """
        об = konung1.Objects.from_game()
        self.assertEqual(об.DYNAMIC_SLOTS, 30)
        живых = sum(1 for г in об.nests if г)
        self.assertEqual(живых, 493)
        разобралось = 0
        for number in konung1.map_numbers():
            for ид in {о["id"] for о in konung1.objects(number)}:
                result = об.simple(ид)
                self.assertIsNotNone(result, f"объект {ид} не разобрался")
                разобралось += 1
        self.assertGreater(разобралось, 500)

    def test_object_palette_comes_from_the_header(self) -> None:
        """Краска объекта — в заголовке записи, но карта её перекрывает.

        Сперва я записала «поле на +0x04 нулевое у всех записей игры» —
        и это утверждение упало на первом же прогоне по всем картам.
        Перекраска в деле: 576 объектов на 30 картах, и все её значения
        лежат в полосе 223…230, которой нет ни у заголовков (76…93), ни
        у плиток земли (11…24).

        Разницу между палитрами видно только в 1:1 — при чужой краске
        спрайт рассыпается крапиной, а ужатая картинка это прячет.
        """
        об = konung1.Objects.from_game()
        свои, перекрашено = set(), 0
        for number in konung1.map_numbers():
            for о in konung1.objects(number):
                if о["palette"] is None:
                    continue
                перекрашено += 1
                свои.add(о["palette"])
        self.assertEqual(перекрашено, 576)
        self.assertEqual(свои, set(range(223, 231)))
        #: у Поречья и Чёрного Бора перекраски нет — краска из заголовка
        for number in (22, 19):
            self.assertTrue(all(о["palette"] is None
                                for о in konung1.objects(number)))
        self.assertEqual(об.header(239)["palette"], 87)
        self.assertEqual(об.header(52)["palette"], 77)


if __name__ == "__main__":
    unittest.main()
