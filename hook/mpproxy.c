/*
 * Посредник MP.DLL — запасная точка внедрения.
 *
 * Игра вызывает LoadLibraryA("MP.DLL") для проигрывания видео, но делает это
 * поздно и не в каждом сценарии: в прогоне со стартом новой игры библиотека
 * так и не загрузилась. Основной вектор — ddrawproxy.c; этот оставлен как
 * запасной и для случаев, когда нужно поймать именно момент показа ролика.
 *
 * Все восемь экспортов пробрасываются в переименованный оригинал
 * MP_real.dll форвардерами уровня линкера: сигнатуры знать не требуется.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "probe.h"

#pragma comment(linker, "/export:CreateAviWnd=MP_real.CreateAviWnd")
#pragma comment(linker, "/export:CreateObjectParented=MP_real.CreateObjectParented")
#pragma comment(linker, "/export:FindAviWnd=MP_real.FindAviWnd")
#pragma comment(linker, "/export:FindObject=MP_real.FindObject")
#pragma comment(linker, "/export:FreeAviWnd=MP_real.FreeAviWnd")
#pragma comment(linker, "/export:PlayAviWnd=MP_real.PlayAviWnd")
#pragma comment(linker, "/export:StopAviWnd=MP_real.StopAviWnd")
#pragma comment(linker, "/export:isPlayingAviWnd=MP_real.isPlayingAviWnd")

BOOL WINAPI DllMain(HINSTANCE self, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        probe_init(self, "MP");
    } else if (reason == DLL_PROCESS_DETACH) {
        probe_stop();
    }
    return TRUE;
}
