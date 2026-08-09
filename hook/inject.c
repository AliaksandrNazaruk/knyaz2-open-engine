/*
 * Инжектор: запускает игру и внедряет в неё нашу библиотеку.
 *
 * Ни один файл игры не подменяется: путь к библиотеке кладётся в память
 * процесса, а удалённый поток вызывает LoadLibraryA.
 *
 * ВАЖНО про момент внедрения. Сначала процесс создавался приостановленным
 * и библиотека грузилась до ResumeThread — и игра падала даже с библиотекой,
 * которая ничего не делает. Причина в том, что у приостановленного процесса
 * ещё не отработал загрузчик Windows (LdrInitializeThunk), а вызывать в
 * таком состоянии LoadLibrary нельзя: структуры загрузчика не готовы.
 *
 * Поэтому процесс сначала отпускается и ему дают проинициализироваться
 * (WaitForInputIdle), и лишь затем внедряется библиотека. Для нашей задачи
 * это ничего не меняет: ловушка всё равно взводится только после загрузки
 * мира, то есть много позже.
 *
 *   inject.exe <путь к konung2.exe> <путь к hook.dll>
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

static int fail(const char *what)
{
    printf("%s: ошибка %lu\n", what, GetLastError());
    return 1;
}

int main(int argc, char **argv)
{
    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    char exe[MAX_PATH], dll[MAX_PATH], dir[MAX_PATH];
    void *remote;
    HMODULE k32;
    FARPROC loadlib;
    HANDLE thread;
    DWORD n, i, cut = 0;
    SIZE_T len;

    if (argc < 3) {
        printf("использование: inject.exe <konung2.exe> <hook.dll>\n");
        return 1;
    }
    if (!GetFullPathNameA(argv[1], MAX_PATH, exe, NULL)) return fail("путь к игре");
    if (!GetFullPathNameA(argv[2], MAX_PATH, dll, NULL)) return fail("путь к библиотеке");

    /* рабочий каталог = каталог игры, иначе она не найдёт свои ресурсы */
    n = lstrlenA(exe);
    for (i = 0; i < n; ++i) {
        if (exe[i] == '\\') cut = i;
    }
    lstrcpynA(dir, exe, cut + 1);
    dir[cut] = 0;

    printf("игра:        %s\n", exe);
    printf("библиотека:  %s\n", dll);
    printf("каталог:     %s\n", dir);

    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(exe, NULL, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        return fail("CreateProcess");
    }
    printf("процесс запущен, pid %lu\n", pi.dwProcessId);

    /* дать загрузчику Windows отработать: в приостановленном процессе
       LoadLibrary вызывать нельзя — структуры загрузчика ещё не готовы */
    WaitForInputIdle(pi.hProcess, 5000);
    Sleep(2500);

    len = (SIZE_T)lstrlenA(dll) + 1;
    remote = VirtualAllocEx(pi.hProcess, NULL, len, MEM_COMMIT | MEM_RESERVE,
                            PAGE_READWRITE);
    if (!remote) {
        TerminateProcess(pi.hProcess, 1);
        return fail("VirtualAllocEx");
    }
    if (!WriteProcessMemory(pi.hProcess, remote, dll, len, NULL)) {
        TerminateProcess(pi.hProcess, 1);
        return fail("WriteProcessMemory");
    }

    k32 = GetModuleHandleA("kernel32.dll");
    loadlib = GetProcAddress(k32, "LoadLibraryA");
    if (!loadlib) {
        TerminateProcess(pi.hProcess, 1);
        return fail("GetProcAddress(LoadLibraryA)");
    }

    thread = CreateRemoteThread(pi.hProcess, NULL, 0,
                                (LPTHREAD_START_ROUTINE)loadlib, remote, 0, NULL);
    if (!thread) {
        TerminateProcess(pi.hProcess, 1);
        return fail("CreateRemoteThread");
    }
    WaitForSingleObject(thread, 10000);
    GetExitCodeThread(thread, &n);
    printf("библиотека загружена, база в процессе: 0x%08lX\n", n);
    CloseHandle(thread);
    VirtualFreeEx(pi.hProcess, remote, 0, MEM_RELEASE);

    if (n == 0) {
        printf("LoadLibrary вернул 0 — библиотека не загрузилась\n");
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        return 1;
    }
    printf("внедрение завершено, игра работает\n");
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
