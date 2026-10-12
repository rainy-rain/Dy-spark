@echo off
rem ============================================================
rem  DY-spark  :  scan, then optionally send
rem
rem   1. checks a browser is attachable
rem   2. scans the chat list and prints who has a spark
rem   3. asks what to do: type a message, send the emoji, or exit
rem
rem  Double-click this file.
rem ============================================================

rem No `chcp 65001` here, deliberately.
rem
rem It looks like the obvious way to keep Chinese friend names readable, but it
rem is both unnecessary and harmful:
rem
rem   * unnecessary - Python writes to a Windows console through the wide-char
rem     API, so console output is correct whatever the code page is
rem   * harmful - under code page 65001, `set /p` fails to read the typed line
rem     and returns empty, so the 0/1 prompt below could never be answered

rem Work from the folder this script lives in, wherever it was launched from.
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
set "CDP=http://127.0.0.1:9222"

if not exist "%PY%" (
  echo [x] Python environment not found:
  echo     %PY%
  echo.
  echo     See README.md for the one-time setup.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  1/3   Browser check
echo ============================================================
echo.
"%PY%" -m dspark edge

echo.
echo ============================================================
echo  2/3   Scanning the chat list
echo        (this step sends nothing)
echo ============================================================
echo.
"%PY%" -m dspark scan --cdp "%CDP%"
if errorlevel 1 (
  echo.
  echo [x] The scan did not succeed, so there is nothing to send to.
  echo     Fix the scan first, then run this again.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  3/3   Send to the conversations that have a spark?
echo.
echo          0  =  send text that I type now
echo          1  =  exit, send nothing
echo          2  =  send the emoji from Douyin's panel
echo                (sending.emoji_label, default: 续火花)
echo ============================================================
echo.

set /a TRIES=0

:choose
set "CHOICE="
set /p "CHOICE=Type 0, 1 or 2, then press Enter: "
if "%CHOICE%"=="0" goto ask_message
if "%CHOICE%"=="1" goto finish
if "%CHOICE%"=="2" goto send_emoji

rem Bounded on purpose. `set /p` sets nothing and returns immediately when the
rem input is exhausted, so an unguarded loop spins forever reprinting the
rem prompt - which is exactly what a test with redirected input did, for five
rem minutes. The exit path here sends nothing, so the failure is harmless.
set /a TRIES+=1
if %TRIES% GEQ 5 (
  echo.
  echo [i] No valid choice after 5 attempts - exiting without sending anything.
  goto finish
)
echo   Please type 0, 1 or 2.
goto choose

:ask_message
echo.
set "MSG="
set /p "MSG=Message to send: "
if not defined MSG (
  echo.
  echo [i] Nothing was typed, so nothing will be sent.
  goto finish
)

echo.
echo ------------------------------------------------------------
echo  Sending now. Watch the browser window to follow along.
echo  Press Ctrl+C if you want to stop.
echo ------------------------------------------------------------
echo.
"%PY%" -m dspark send --cdp "%CDP%" --yes --message "%MSG%"
goto finish

:send_emoji
echo.
echo ------------------------------------------------------------
echo  Sending the emoji now. Watch the browser window - the panel
echo  opens and closes once per friend. Press Ctrl+C to stop.
echo ------------------------------------------------------------
echo.
"%PY%" -m dspark send --cdp "%CDP%" --yes --emoji
goto finish

:finish
echo.
echo ------------------------------------------------------------
echo  Finished. This window stays open so the output can be read.
echo ------------------------------------------------------------
pause
