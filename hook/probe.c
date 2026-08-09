/*
 * Чтение состояния «Князя 2» изнутри процесса.
 *
 * На этом шаге только наблюдение: надо доказать, что адреса, выведенные
 * статическим разбором exe, совпадают с настоящими в работающей игре.
 * Ни один байт игры не изменяется.
 *
 * Зависимостей от CRT нет: журнал пишется через CreateFile/WriteFile,
 * форматирование — wvsprintfA из user32. Динамический CRT внутри чужого
 * процесса может просто отсутствовать, и тогда библиотека не загрузится.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "probe.h"

/* Адреса получены разбором konung2.exe; см. FORMATS.md */
#define ADDR_UNITS       0x007B3C08u   /* 2000 записей по 0x100        */
#define ADDR_PARTIES     0x0071E56Cu   /* 200 записей по 0x100         */
#define ADDR_VILLAGES    0x0083D408u   /* 12 записей по 0x4A1          */
#define ADDR_CUR_MAP     0x008496C8u   /* номер текущей карты          */
#define ADDR_CUR_PARTY   0x0084950Cu   /* указатель на отряд игрока    */
#define ADDR_VILLAGE_PTR 0x00849538u   /* указатель на поселение карты */

#define UNIT_STRIDE   0x100u
#define PARTY_STRIDE  0x100u
#define EXPECTED_BASE 0x00400000u

#define U8(a)  (*(volatile unsigned char *)(UINT_PTR)(a))
#define U16(a) (*(volatile unsigned short *)(UINT_PTR)(a))
#define I16(a) (*(volatile short *)(UINT_PTR)(a))
#define U32(a) (*(volatile unsigned int *)(UINT_PTR)(a))

static char g_log_path[MAX_PATH];
static volatile LONG g_stop;
static int g_watch_on;          /* ловушка взводится только после загрузки мира */

void log_line(const char *fmt, ...)
{
    char buf[1024];
    va_list args;
    int len;
    HANDLE h;
    DWORD written;

    if (!g_log_path[0]) {
        return;
    }
    va_start(args, fmt);
    len = wvsprintfA(buf, fmt, args);
    va_end(args);
    if (len < 0 || len > (int)sizeof(buf) - 3) {
        return;
    }
    buf[len++] = '\r';
    buf[len++] = '\n';

    h = CreateFileA(g_log_path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL,
                    OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        return;
    }
    WriteFile(h, buf, (DWORD)len, &written, NULL);
    CloseHandle(h);
}

/* Читать разрешено только по действительно отображённой памяти. */
static int readable(UINT_PTR addr, SIZE_T size)
{
    MEMORY_BASIC_INFORMATION mbi;
    DWORD ok = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY
             | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE;
    if (!VirtualQuery((LPCVOID)addr, &mbi, sizeof(mbi))) {
        return 0;
    }
    if (mbi.State != MEM_COMMIT || (mbi.Protect & ok) == 0) {
        return 0;
    }
    return (addr + size) <= ((UINT_PTR)mbi.BaseAddress + mbi.RegionSize);
}

static void dump_state(int n)
{
    UINT_PTR cur_party, hero;
    unsigned int map;
    int units_here = 0, parties_here = 0, i;

    if (!readable(ADDR_CUR_MAP, 4)) {
        log_line("[%d] глобалы ещё не заполнены", n);
        return;
    }
    map = U32(ADDR_CUR_MAP);
    cur_party = (UINT_PTR)U32(ADDR_CUR_PARTY);
    log_line("[%d] карта=%d отряд_игрока=0x%08X поселение=0x%08X",
             n, (int)map, (unsigned)cur_party, (unsigned)U32(ADDR_VILLAGE_PTR));

    if (readable(cur_party, PARTY_STRIDE)) {
        unsigned base = U16(cur_party + 0x00);
        unsigned cnt = U8(cur_party + 0x1C);
        log_line("    отряд: база=%u кол-во=%u карта=%u", base, cnt, U16(cur_party + 0x08));
        hero = ADDR_UNITS + (UINT_PTR)base * UNIT_STRIDE;
        if (readable(hero, UNIT_STRIDE)) {
            log_line("    герой: клетка=(строка %u, столбец %u) hp=%d уровень=%u имя=%u",
                     U8(hero + 0x12), U8(hero + 0x14), (int)I16(hero + 0x4E),
                     U8(hero + 0xF3), U8(hero + 0xF0));
        }
    }

    for (i = 0; i < 200; ++i) {
        UINT_PTR p = ADDR_PARTIES + (UINT_PTR)i * PARTY_STRIDE;
        if (!readable(p, PARTY_STRIDE)) {
            break;
        }
        if (U8(p + 0x1C) > 0 && U16(p + 0x08) == map) {
            ++parties_here;
            units_here += U8(p + 0x1C);
        }
    }
    log_line("    на этой карте: отрядов %d, юнитов %d", parties_here, units_here);
}

static DWORD WINAPI probe_thread(LPVOID unused)
{
    HMODULE exe = GetModuleHandleA(NULL);
    int n = 0;
    (void)unused;

    log_line("--- зонд запущен, база exe=0x%08X (ожидалась 0x%08X) ---",
             (unsigned)(UINT_PTR)exe, EXPECTED_BASE);
    if ((UINT_PTR)exe != EXPECTED_BASE) {
        log_line("образ загружен не по своей базе — адреса смещены, чтение отменено");
        return 0;
    }
    /*
     * Ловушка взводится НЕ при старте, а только когда мир уже загружен.
     * Сторожевая страница на .bss мешает инициализации движка: игра
     * обращается к этой памяти задолго до отрисовки объектов, и запуск
     * с ловушкой падал, тогда как чистый запуск работал.
     */
    while (!g_stop) {
        int armed = 0;
        __try {
            dump_state(n);
            if (!armed && readable(ADDR_CUR_MAP, 4) && U32(ADDR_CUR_MAP) > 0
                && U32(ADDR_CUR_MAP) < 100) {
                if (!g_watch_on) {
                    g_watch_on = 1;
                    log_line("мир загружен (карта=%u) — взводим ловушку",
                             U32(ADDR_CUR_MAP));
                    watch_start();
                } else {
                    watch_rearm();
                }
                armed = 1;
            }
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            log_line("[%d] исключение при чтении", n);
        }
        ++n;
        Sleep(2000);
    }
    watch_stop();
    return 0;
}

void probe_init(HINSTANCE self, const char *tag)
{
    DWORD len, i, cut = 0;
    len = GetModuleFileNameA(self, g_log_path, MAX_PATH);
    for (i = 0; i < len; ++i) {
        if (g_log_path[i] == '\\') {
            cut = i + 1;
        }
    }
    lstrcpyA(g_log_path + cut, "konung_hook.log");
    log_line("=== посредник %s загружен процессом ===", tag);
    CreateThread(NULL, 0, probe_thread, NULL, 0, NULL);
}

void probe_stop(void)
{
    InterlockedExchange(&g_stop, 1);
}
