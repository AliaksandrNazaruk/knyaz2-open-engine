/*
 * Минимальная библиотека для внедрения: пишет одну строку и больше ничего.
 *
 * Нужна для бисекции. Игра падает и после того, как ловушка перестала
 * взводиться на старте, значит виноват либо поток зонда, либо сама
 * инжекция. Здесь нет ни потока, ни таймеров, ни обработчиков исключений —
 * только запись факта загрузки. Если с этой библиотекой игра живёт,
 * виноват поток; если падает — виновата инжекция как таковая.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

static void note(HINSTANCE self, const char *text)
{
    char path[MAX_PATH];
    DWORD n, i, cut = 0, written;
    HANDLE h;

    n = GetModuleFileNameA(self, path, MAX_PATH);
    for (i = 0; i < n; ++i) {
        if (path[i] == '\\') {
            cut = i + 1;
        }
    }
    lstrcpyA(path + cut, "konung_hook.log");

    h = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL,
                    OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        return;
    }
    WriteFile(h, text, (DWORD)lstrlenA(text), &written, NULL);
    WriteFile(h, "\r\n", 2, &written, NULL);
    CloseHandle(h);
}

BOOL WINAPI DllMain(HINSTANCE self, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        note(self, "=== minimal hook loaded, nothing else is running ===");
    }
    return TRUE;
}
