@echo off
rem Build 32-bit proxy DLLs for Konung 2.
rem ASCII only: cmd.exe reads .bat files in the OEM codepage and mangles UTF-8.
rem /MT keeps the static CRT so the DLL loads without VCRUNTIME140.dll.

setlocal
set VCVARS="%ProgramFiles(x86)%\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars32.bat"
if not exist %VCVARS% (
    echo vcvars32.bat not found: %VCVARS%
    exit /b 1
)
call %VCVARS% >nul
if errorlevel 1 exit /b 1

pushd "%~dp0"
if not exist build mkdir build

echo [0/4] bare ddraw forwarder (no probe, no trap) -^> build\bare\ddraw.dll
if not exist build\bare mkdir build\bare
cl /nologo /W3 /O2 /MT /LD /Fe:build\bare\ddraw.dll /Fo:build\bare\ /Fd:build\bare\ ddrawbare.c /link /OUT:build\bare\ddraw.dll
if errorlevel 1 goto fail

echo [1/4] shared probe
cl /nologo /W3 /O2 /MT /c /Fo:build\probe.obj probe.c
if errorlevel 1 goto fail

echo [2/4] memory watch (guard page trap)
cl /nologo /W3 /O2 /MT /c /Fo:build\watch.obj watch.c
if errorlevel 1 goto fail

echo [3/4] ddraw.dll proxy (loaded at process start, static import)
cl /nologo /W3 /O2 /MT /LD /Fe:build\ddraw.dll /Fo:build\ddrawproxy.obj ddrawproxy.c build\probe.obj build\watch.obj /link /OUT:build\ddraw.dll user32.lib
if errorlevel 1 goto fail

echo [4/4] MP.dll proxy (loaded later by the video player)
cl /nologo /W3 /O2 /MT /LD /Fe:build\MP.dll /Fo:build\mpproxy.obj mpproxy.c build\probe.obj build\watch.obj /link /OUT:build\MP.dll user32.lib
if errorlevel 1 goto fail

echo [5/5] hook dll + injector (nothing is replaced in the game folder)
cl /nologo /W3 /O2 /MT /LD /Fe:build\konung_hook.dll /Fo:build\hookdll.obj hookdll.c build\probe.obj build\watch.obj /link /OUT:build\konung_hook.dll user32.lib
if errorlevel 1 goto fail
cl /nologo /W3 /O2 /MT /LD /Fe:build\konung_bare.dll /Fo:build\hookbare.obj hookbare.c /link /OUT:build\konung_bare.dll
if errorlevel 1 goto fail

rem /SUBSYSTEM:WINDOWS so no console window appears and steals the focus
rem from the fullscreen game; main() still runs via mainCRTStartup.
cl /nologo /W3 /O2 /MT /Fe:build\inject.exe /Fo:build\inject.obj inject.c /link /OUT:build\inject.exe /SUBSYSTEM:WINDOWS /ENTRY:mainCRTStartup user32.lib
if errorlevel 1 goto fail

popd
echo OK: konung_hook.dll + inject.exe (and the ddraw/MP proxies)
exit /b 0

:fail
popd
echo BUILD FAILED
exit /b 1
