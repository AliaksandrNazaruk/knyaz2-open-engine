/*
 * Библиотека для внедрения в процесс игры.
 *
 * В отличие от посредника, ничего не подменяет и никуда не форвардит:
 * её загружает инжектор удалённым потоком уже после старта процесса.
 * Вся полезная часть — общий зонд и ловушка на таблицу кадров.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "probe.h"

BOOL WINAPI DllMain(HINSTANCE self, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        probe_init(self, "inject");
    } else if (reason == DLL_PROCESS_DETACH) {
        probe_stop();
    }
    return TRUE;
}
