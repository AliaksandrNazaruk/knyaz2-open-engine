@echo off
rem Launch Konung 2 with the hook library injected.
rem ASCII only: cmd.exe mangles UTF-8 in .bat files.
rem
rem The game is a fullscreen DirectDraw app and quits as soon as it loses
rem focus. A console window left on screen is enough to kill it, so this
rem script starts the injector detached and closes itself immediately.
rem
rem The game folder is never modified: the library is loaded into the
rem process by a remote thread after the process is created suspended.

setlocal
set RIG=%USERPROFILE%\Documents\Knyaz2Test
set HOOKDIR=%USERPROFILE%\Documents\Knyaz2Modding\hook\build

if not exist "%HOOKDIR%\inject.exe" (
    echo inject.exe not found - run build.bat first
    pause
    exit /b 1
)
copy /Y "%HOOKDIR%\konung_hook.dll" "%RIG%\konung_hook.dll" >nul
del "%RIG%\konung_hook.log" 2>nul

rem start detached, then exit at once so no window steals the focus
start "" /b "%HOOKDIR%\inject.exe" "%RIG%\konung2.exe" "%RIG%\konung_hook.dll"
exit
