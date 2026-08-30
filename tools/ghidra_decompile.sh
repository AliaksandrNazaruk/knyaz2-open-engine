#!/usr/bin/env bash
# Декомпиляция exe игры в engine/decompiled* (Ghidra headless).
#
# Первый прогон анализирует бинарник и складывает проект в engine/ghidra_project,
# дальше можно гонять с --reuse: анализ не повторяется, только выгрузка.
#
#   tools/ghidra_decompile.sh                   # «Кровь Титанов»
#   tools/ghidra_decompile.sh --reuse           # только выгрузка, по готовому
#   tools/ghidra_decompile.sh --game legend     # «Продолжение легенды»
#
# ЧИСЛА У КАЖДОЙ СБОРКИ СВОИ, и берутся они из профиля игры, а не пишутся
# сюда руками: границы секции кода и таблица обработчиков разные, и подсунуть
# чужие значит потерять ровно те точки входа, ради которых проход и заведён.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${GHIDRA_TOOLS:-/c/Users/User/Tools}"
GHIDRA="$(ls -d "$TOOLS"/ghidra_*_PUBLIC 2>/dev/null | head -1)"
JDK="$(ls -d "$TOOLS"/jdk-* 2>/dev/null | head -1)"

GAME_KEY="canon"
REUSE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --reuse) REUSE="1"; shift ;;
        --game) GAME_KEY="$2"; shift 2 ;;
        *) echo "непонятный довод: $1"; exit 1 ;;
    esac
done

[ -n "$GHIDRA" ] || { echo "не нашёл Ghidra в $TOOLS"; exit 1; }
[ -n "$JDK" ] || { echo "не нашёл JDK в $TOOLS"; exit 1; }

export JAVA_HOME="$JDK"
export PATH="$JDK/bin:$PATH"

# Профиль игры — единственный владелец адресов. Отсюда же берётся путь к exe.
# Поля разделены табуляцией: в пути к игре есть пробелы.
IFS=$'\t' read -r EXE_PATH EXE_NAME CODE_LO CODE_HI HANDLERS_VA HANDLERS_N OUT_NAME <<EOF
$(cd "$REPO" && PYTHONIOENCODING=utf-8 python tools/ghidra_target.py "$GAME_KEY")
EOF

# Профиль отдаёт виндовый путь; bash работает с posix-видом, а .bat снова с
# виндовым — поэтому переводим туда и обратно, а не тащим одну форму насквозь.
EXE_POSIX="$(cygpath -u "$EXE_PATH")"
[ -f "$EXE_POSIX" ] || { echo "не нашёл $EXE_PATH"; exit 1; }

# КИРИЛЛИЦА В ПУТИ РОНЯЕТ ЗАПУСК. analyzeHeadless — это .bat, то есть cmd, и
# на «…\Князь - Коллекционное издание\…» он падает с «was unexpected at this
# time». Поэтому exe кладётся под ASCII-путь и импортируется оттуда; игры это
# не касается, читается копия.
STAGE="$REPO/engine/ghidra_import"
mkdir -p "$STAGE"
if [ ! -f "$STAGE/$EXE_NAME" ] || [ "$EXE_POSIX" -nt "$STAGE/$EXE_NAME" ]; then
    echo "кладу копию под ASCII-путь: engine/ghidra_import/$EXE_NAME"
    cp "$EXE_POSIX" "$STAGE/$EXE_NAME"
fi
EXE_PATH="$(cygpath -w "$STAGE/$EXE_NAME")"

PROJECT="$REPO/engine/ghidra_project"
OUT="$REPO/engine/$OUT_NAME"
mkdir -p "$PROJECT" "$OUT"

echo "цель: $EXE_NAME"
echo "  код $CODE_LO..$CODE_HI, обработчики $HANDLERS_VA на $HANDLERS_N"
echo "  выгрузка в engine/$OUT_NAME"

# Пути для .bat переводим в виндовые: analyzeHeadless запускается cmd-скриптом.
win() { cygpath -w "$1"; }

if [ -n "$REUSE" ]; then
    MODE=(-process "$EXE_NAME" -noanalysis)
else
    MODE=(-import "$EXE_PATH" -overwrite)
fi

# MakeMissingFunctions идёт ПЕРЕД анализом: Ghidra заводит функцию по CALL, а
# точки входа из таблиц указателей (обработчики разговора, оконная процедура)
# она пропускает. Без этого прохода выгрузка теряла 6.6% секции кода — и ровно
# в тех подсистемах, которые нужны порту.
"$GHIDRA/support/analyzeHeadless.bat" \
    "$(win "$PROJECT")" knyaz2 \
    "${MODE[@]}" \
    -scriptPath "$(win "$REPO/tools/ghidra")" \
    -preScript MakeMissingFunctions.java "$CODE_LO" "$CODE_HI" \
               "$HANDLERS_VA" "$HANDLERS_N" \
    -postScript ExportDecompiled.java "$(win "$OUT")" \
    -max-cpu "$(nproc 2>/dev/null || echo 4)"

echo
echo "готово. дальше:"
echo "  python tools/engine_map.py todo"
echo "  python tools/engine_map.py info 0x425DB4"
