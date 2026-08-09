/*
 * Голый форвардер ddraw.dll — только проброс, без единой посторонней строки.
 *
 * Нужен, чтобы разделить две причины раннего завершения игры: мешает сама
 * подмена библиотеки или наш код внутри процесса (поток зонда, журнал,
 * сторожевая страница). Здесь нет ни потоков, ни файлов, ни обработчиков
 * исключений — только загрузка системной библиотеки и переход в неё.
 *
 * Игра импортирует из DDRAW.dll ровно одну функцию — DirectDrawCreate
 * (проверено dumpbin), но экспортируем и соседние: если библиотеку тронет
 * что-то ещё в системе, отсутствие имени приведёт к отказу загрузки.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#define THUNK(name)                                                         \
    static FARPROC real_##name;                                             \
    __declspec(naked) void Fake_##name(void)                                \
    {                                                                       \
        __asm { jmp dword ptr [real_##name] }                               \
    }

THUNK(DirectDrawCreate)
THUNK(DirectDrawCreateEx)
THUNK(DirectDrawCreateClipper)
THUNK(DirectDrawEnumerateA)
THUNK(DirectDrawEnumerateW)
THUNK(DirectDrawEnumerateExA)
THUNK(DirectDrawEnumerateExW)

#pragma comment(linker, "/export:DirectDrawCreate=_Fake_DirectDrawCreate")
#pragma comment(linker, "/export:DirectDrawCreateEx=_Fake_DirectDrawCreateEx")
#pragma comment(linker, "/export:DirectDrawCreateClipper=_Fake_DirectDrawCreateClipper")
#pragma comment(linker, "/export:DirectDrawEnumerateA=_Fake_DirectDrawEnumerateA")
#pragma comment(linker, "/export:DirectDrawEnumerateW=_Fake_DirectDrawEnumerateW")
#pragma comment(linker, "/export:DirectDrawEnumerateExA=_Fake_DirectDrawEnumerateExA")
#pragma comment(linker, "/export:DirectDrawEnumerateExW=_Fake_DirectDrawEnumerateExW")

BOOL WINAPI DllMain(HINSTANCE self, DWORD reason, LPVOID reserved)
{
    char path[MAX_PATH];
    UINT len;
    HMODULE real;

    (void)reserved;
    if (reason != DLL_PROCESS_ATTACH) {
        return TRUE;
    }
    DisableThreadLibraryCalls(self);

    len = GetSystemDirectoryA(path, MAX_PATH);
    if (!len || len > MAX_PATH - 12) {
        return FALSE;
    }
    lstrcpyA(path + len, "\\ddraw.dll");
    real = LoadLibraryA(path);
    if (!real) {
        return FALSE;
    }
#define BIND(name) real_##name = GetProcAddress(real, #name)
    BIND(DirectDrawCreate);
    BIND(DirectDrawCreateEx);
    BIND(DirectDrawCreateClipper);
    BIND(DirectDrawEnumerateA);
    BIND(DirectDrawEnumerateW);
    BIND(DirectDrawEnumerateExA);
    BIND(DirectDrawEnumerateExW);
#undef BIND
    return real_DirectDrawCreate ? TRUE : FALSE;
}
