@echo off
rem Bisection run: inject a library that does nothing but log one line.
rem If the game survives with this, the probe thread is to blame.
rem If it still dies, the injection itself is the problem.
rem ASCII only: cmd.exe mangles UTF-8 in .bat files.

setlocal
set RIG=%USERPROFILE%\Documents\Knyaz2Test
set HOOKDIR=%USERPROFILE%\Documents\Knyaz2Modding\hook\build

copy /Y "%HOOKDIR%\konung_bare.dll" "%RIG%\konung_bare.dll" >nul
del "%RIG%\konung_hook.log" 2>nul

start "" /b "%HOOKDIR%\inject.exe" "%RIG%\konung2.exe" "%RIG%\konung_bare.dll"
exit
