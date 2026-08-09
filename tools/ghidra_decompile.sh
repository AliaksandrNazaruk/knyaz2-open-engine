#!/usr/bin/env bash
# Декомпиляция konung2.exe в engine/decompiled (Ghidra headless).
#
# Первый прогон анализирует бинарник и складывает проект в engine/ghidra_project,
# дальше можно гонять с --reuse: анализ не повторяется, только выгрузка.
#
#   tools/ghidra_decompile.sh            # полный прогон
#   tools/ghidra_decompile.sh --reuse    # только выгрузка, по готовому проекту
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${GHIDRA_TOOLS:-/c/Users/User/Tools}"
GHIDRA="$(ls -d "$TOOLS"/ghidra_*_PUBLIC 2>/dev/null | head -1)"
JDK="$(ls -d "$TOOLS"/jdk-* 2>/dev/null | head -1)"
GAME="${KONUNG2_DIR:-/c/Program Files (x86)/Князь - Коллекционное издание/02. Князь 2 - Кровь Титанов}"

[ -n "$GHIDRA" ] || { echo "не нашёл Ghidra в $TOOLS"; exit 1; }
[ -n "$JDK" ] || { echo "не нашёл JDK в $TOOLS"; exit 1; }
[ -f "$GAME/konung2.exe" ] || { echo "не нашёл konung2.exe в $GAME"; exit 1; }

export JAVA_HOME="$JDK"
export PATH="$JDK/bin:$PATH"

PROJECT="$REPO/engine/ghidra_project"
OUT="$REPO/engine/decompiled"
mkdir -p "$PROJECT" "$OUT"

# Пути для .bat переводим в виндовые: analyzeHeadless запускается cmd-скриптом.
win() { cygpath -w "$1"; }

if [ "${1:-}" = "--reuse" ]; then
    MODE=(-process konung2.exe -noanalysis)
else
    MODE=(-import "$(win "$GAME/konung2.exe")" -overwrite)
fi

# MakeMissingFunctions идёт ПЕРЕД анализом: Ghidra заводит функцию по CALL, а
# точки входа из таблиц указателей (обработчики разговора 0x462E90, оконная
# процедура 0x42F22C) она пропускает. Без этого прохода выгрузка теряла 6.6%
# секции кода — и ровно в тех подсистемах, которые нужны порту.
"$GHIDRA/support/analyzeHeadless.bat" \
    "$(win "$PROJECT")" knyaz2 \
    "${MODE[@]}" \
    -scriptPath "$(win "$REPO/tools/ghidra")" \
    -preScript MakeMissingFunctions.java \
    -postScript ExportDecompiled.java "$(win "$OUT")" \
    -max-cpu "$(nproc 2>/dev/null || echo 4)"

echo
echo "готово. дальше:"
echo "  python tools/engine_map.py todo"
echo "  python tools/engine_map.py info 0x425DB4"
