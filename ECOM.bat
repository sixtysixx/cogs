@ECHO OFF
:RED
CALL "%userprofile%\redenv\Scripts\activate.bat"
python -O -m redbot ECOM --team-members-are-owners

IF %ERRORLEVEL% == 1 GOTO RESTART_RED
IF %ERRORLEVEL% == 26 GOTO RESTART_RED
EXIT /B %ERRORLEVEL%

:RESTART_RED
ECHO Restarting Red...
GOTO RED
