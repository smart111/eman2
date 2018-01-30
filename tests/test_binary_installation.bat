set INSTALLER_DIR=C:\Users\EMAN\workspace\win-installers
set INSTALLER_FILE=eman2.win64.exe
set INSTALLATION_DIR=eman2.win64

rmdir /q /s %INSTALLER_DIR%\%INSTALLATION_DIR%

start /wait "" %INSTALLER_DIR%\%INSTALLER_FILE% /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=%INSTALLER_DIR%\%INSTALLATION_DIR%
if errorlevel 1 exit 1
