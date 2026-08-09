/*
 * Посредник ddraw.dll — надёжная точка внедрения в «Князь 2».
 *
 * Игра статически импортирует DDRAW.dll, а такие библиотеки Windows ищет
 * сначала в папке приложения. Значит наша копия загрузится ещё до первой
 * инструкции игры — в отличие от MP.DLL, которую движок подгружает поздно
 * и не в каждом сценарии.
 *
 * Экспорты уходят в системный ddraw «голым» переходом: стек и соглашение
 * вызова сохраняются как есть, поэтому сигнатуры функций знать не нужно.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "probe.h"

#define EXPORT_THUNK(name)                                                  \
    static FARPROC real_##name;                                             \
    __declspec(naked) void Fake_##name(void)                                \
    {                                                                       \
        __asm { jmp dword ptr [real_##name] }                               \
    }

EXPORT_THUNK(DirectDrawCreate)
EXPORT_THUNK(DirectDrawCreateEx)
EXPORT_THUNK(DirectDrawCreateClipper)
EXPORT_THUNK(DirectDrawEnumerateA)
EXPORT_THUNK(DirectDrawEnumerateW)
EXPORT_THUNK(DirectDrawEnumerateExA)
EXPORT_THUNK(DirectDrawEnumerateExW)
EXPORT_THUNK(DllGetClassObject)
EXPORT_THUNK(DllCanUnloadNow)

#pragma comment(linker, "/export:DirectDrawCreate=_Fake_DirectDrawCreate")
#pragma comment(linker, "/export:DirectDrawCreateEx=_Fake_DirectDrawCreateEx")
#pragma comment(linker, "/export:DirectDrawCreateClipper=_Fake_DirectDrawCreateClipper")
#pragma comment(linker, "/export:DirectDrawEnumerateA=_Fake_DirectDrawEnumerateA")
#pragma comment(linker, "/export:DirectDrawEnumerateW=_Fake_DirectDrawEnumerateW")
#pragma comment(linker, "/export:DirectDrawEnumerateExA=_Fake_DirectDrawEnumerateExA")
#pragma comment(linker, "/export:DirectDrawEnumerateExW=_Fake_DirectDrawEnumerateExW")
#pragma comment(linker, "/export:DllGetClassObject=_Fake_DllGetClassObject,PRIVATE")
#pragma comment(linker, "/export:DllCanUnloadNow=_Fake_DllCanUnloadNow,PRIVATE")

static HMODULE g_real;

static void bind_real(void)
{
    char path[MAX_PATH];
    UINT len = GetSystemDirectoryA(path, MAX_PATH);
    if (!len || len > MAX_PATH - 12) {
        return;
    }
    lstrcpyA(path + len, "\\ddraw.dll");
    g_real = LoadLibraryA(path);
    if (!g_real) {
        return;
    }
#define BIND(name) real_##name = GetProcAddress(g_real, #name)
    BIND(DirectDrawCreate);
    BIND(DirectDrawCreateEx);
    BIND(DirectDrawCreateClipper);
    BIND(DirectDrawEnumerateA);
    BIND(DirectDrawEnumerateW);
    BIND(DirectDrawEnumerateExA);
    BIND(DirectDrawEnumerateExW);
    BIND(DllGetClassObject);
    BIND(DllCanUnloadNow);
#undef BIND
}

BOOL WINAPI DllMain(HINSTANCE self, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        bind_real();
        probe_init(self, "ddraw");
        log_line("системный ddraw: 0x%08X, DirectDrawCreate: 0x%08X",
                 (unsigned)(UINT_PTR)g_real, (unsigned)(UINT_PTR)real_DirectDrawCreate);
    } else if (reason == DLL_PROCESS_DETACH) {
        probe_stop();
    }
    return TRUE;
}
