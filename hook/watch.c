/*
 * Ловушка на память: кто обращается к таблице кадров объекта.
 *
 * Статический поиск распаковщика пикселей себя исчерпал — сигнатура
 * «0x80 рядом с 0x7F» встречается в коде слишком часто. Поэтому ловим
 * процедуру за руку в работающей игре.
 *
 * Приём: на страницу с таблицей кадров ставится флаг PAGE_GUARD. Любое
 * обращение к ней вызывает STATUS_GUARD_PAGE_VIOLATION, а векторный
 * обработчик записывает в журнал EIP обратившейся инструкции и адрес,
 * к которому шло обращение. Дальше от этого EIP до распаковщика — один шаг.
 *
 * Сторож снимается системой при первом же срабатывании, поэтому поток-зонд
 * периодически ставит его заново: так ловятся разные места обращения, а не
 * только самое первое.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "probe.h"

/* Массив заголовков динамических объектов: 0x72CCAC + slot * 0x1728.
   У слота 0 таблица кадров лежит на +0x728 (8 байт заголовка + 1824 анимаций). */
#define HDR_ARRAY   0x0072CCACu
#define HDR_STRIDE  0x1728u
#define FRAMES_OFF  0x0728u

static void *g_watch_addr;
static SIZE_T g_watch_size;
static void *g_veh;
static volatile LONG g_caught;

#define MAX_CATCH 40

static int arm_guard(void)
{
    DWORD old;
    if (!g_watch_addr) {
        return 0;
    }
    return VirtualProtect(g_watch_addr, g_watch_size,
                          PAGE_READWRITE | PAGE_GUARD, &old) ? 1 : 0;
}

static LONG CALLBACK on_exception(EXCEPTION_POINTERS *info)
{
    EXCEPTION_RECORD *er = info->ExceptionRecord;

    if (er->ExceptionCode == STATUS_GUARD_PAGE_VIOLATION) {
        if (InterlockedIncrement(&g_caught) <= MAX_CATCH) {
            const char *kind = er->ExceptionInformation[0] ? "запись" : "чтение";
            log_line("ЛОВУШКА: %s по 0x%08X из кода 0x%08X",
                     kind,
                     (unsigned)er->ExceptionInformation[1],
                     (unsigned)info->ContextRecord->Eip);
        }
        /* сторож уже снят системой — выполнение продолжится штатно */
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

void watch_start(void)
{
    UINT_PTR frames = HDR_ARRAY + FRAMES_OFF;   /* таблица кадров слота 0 */

    g_watch_addr = (void *)frames;
    g_watch_size = 0x1000;                      /* одна страница */

    g_veh = AddVectoredExceptionHandler(1, on_exception);
    if (!g_veh) {
        log_line("ловушка: не удалось поставить обработчик исключений");
        return;
    }
    if (arm_guard()) {
        log_line("ловушка взведена на 0x%08X (%u байт), ждём обращений",
                 (unsigned)frames, (unsigned)g_watch_size);
    } else {
        log_line("ловушка: VirtualProtect отказал по 0x%08X — "
                 "память ещё не выделена, повторим позже", (unsigned)frames);
    }
}

/* Вызывается зондом раз в цикл: сторож после срабатывания надо ставить заново. */
void watch_rearm(void)
{
    if (g_veh && g_caught < MAX_CATCH) {
        arm_guard();
    }
}

void watch_stop(void)
{
    if (g_veh) {
        RemoveVectoredExceptionHandler(g_veh);
        g_veh = NULL;
    }
}
