@echo off
rem ============================================================
rem  DY-spark  :  check the environment, start a browser, scan,
rem               then ask whether to send.
rem
rem  Double-click this file.
rem
rem  Deliberately ASCII-only, and deliberately no `chcp 65001`.
rem
rem  cmd.exe parses a .bat file byte by byte using the console code
rem  page (936 here). A UTF-8 Chinese comment is therefore decoded as
rem  GBK, which desynchronises the parser: `rem` lines get executed as
rem  commands and characters get truncated. Measured, not theorised.
rem
rem  `chcp 65001` would fix the parsing, but it makes `set /p` below
rem  read nothing at all - also measured. The two are mutually
rem  exclusive, so this file stays ASCII and the Chinese prose lives
rem  in the README, which every URL here points at.
rem ============================================================

setlocal

rem Run from this file's own folder, wherever it was launched from.
cd /d "%~dp0"

set "CDP=http://127.0.0.1:9222"
set "PORT=9222"
set "FAILED=0"
set "PY="
set "PYVER="

echo.
echo ============================================================
echo  1/4   Environment check
echo ============================================================
echo.

call :chk_python
call :chk_config
call :chk_playwright
call :chk_browser
call :chk_chromium
call :chk_login
call :chk_port
call :chk_network

echo.
if %FAILED% GTR 0 goto :env_failed
echo   ------------------------------------------------------------
echo   All required checks passed. Continuing.
echo   ------------------------------------------------------------
goto :stage_browser

:env_failed
echo   ------------------------------------------------------------
echo   %FAILED% required item(s) must be fixed first.
echo   Each one above says how.
echo   ------------------------------------------------------------
echo.
pause
exit /b 1

rem ============================================================
rem  2/4  Start a browser dspark can drive
rem ============================================================
:stage_browser
echo.
echo ============================================================
echo  2/4   Starting a browser for dspark to drive
echo        (your own Edge windows are left alone)
echo ============================================================
echo.
"%PY%" -m dspark edge
if errorlevel 1 (
  echo.
  echo   [x] The browser did not start. The message above says why.
  echo       For every page action:
  echo           .venv\Scripts\python.exe -m dspark edge -v
  echo.
  pause
  exit /b 1
)

rem ============================================================
rem  3/4  Scan
rem ============================================================
echo.
echo ============================================================
echo  3/4   Scanning the chat list
echo        (this step sends nothing)
echo ============================================================
echo.
"%PY%" -m dspark scan --cdp "%CDP%"
if errorlevel 1 (
  echo.
  echo   [x] The scan did not succeed, so there is nothing to send to.
  echo       The message above says which part failed. For every page action:
  echo           .venv\Scripts\python.exe -m dspark scan --cdp %CDP% -v
  echo.
  pause
  exit /b 1
)

rem ============================================================
rem  4/4  Ask
rem ============================================================
echo.
echo ============================================================
echo  4/4   Send to the conversations that have a spark?
echo.
echo          0  =  send text I type now
echo          1  =  exit, send nothing
echo          2  =  send the emoji from Douyin's panel
echo               (sending.emoji_label, default: the streak emoji)
echo ============================================================
echo.

set /a TRIES=0

:choose
set "CHOICE="
set /p "CHOICE=Type 0, 1 or 2, then press Enter: "
if "%CHOICE%"=="0" goto :ask_message
if "%CHOICE%"=="1" goto :finish
if "%CHOICE%"=="2" goto :send_emoji

rem Bounded on purpose: set /p returns immediately and sets nothing
rem when the input is exhausted, so an unguarded loop reprints the
rem prompt forever (measured: five minutes of spinning).
set /a TRIES+=1
if %TRIES% GEQ 5 (
  echo.
  echo   [i] No valid choice after 5 attempts. Exiting, sending nothing.
  goto :finish
)
echo   Please type 0, 1 or 2.
goto :choose

:ask_message
echo.
set "MSG="
set /p "MSG=Message to send: "
if not defined MSG (
  echo.
  echo   [i] Nothing was typed, so nothing will be sent.
  goto :finish
)
echo.
echo   ------------------------------------------------------------
echo   Sending now. Watch the browser window to follow along.
echo   Press Ctrl+C to stop.
echo   ------------------------------------------------------------
echo.
"%PY%" -m dspark send --cdp "%CDP%" --yes --message "%MSG%"
goto :finish

:send_emoji
echo.
echo   ------------------------------------------------------------
echo   Sending the emoji now. The panel opens once per friend.
echo   Watch the browser window. Press Ctrl+C to stop.
echo   ------------------------------------------------------------
echo.
"%PY%" -m dspark send --cdp "%CDP%" --yes --emoji
goto :finish

:finish
echo.
echo   ------------------------------------------------------------
echo   Finished. This window stays open so the output can be read.
echo   ------------------------------------------------------------
pause
exit /b 0


rem ============================================================
rem  The eight environment checks
rem ============================================================

rem ---------- [1] Python 3.10+ ----------
:chk_python
echo   [1] Python 3.10 or newer

if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
) else (
  where python >nul 2>&1
  if not errorlevel 1 set "PY=python"
)

if not defined PY goto :chk_python_bad

rem Let Python compare the version; splitting the string in batch is
rem far more fragile than asking the interpreter itself.
"%PY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto :chk_python_old

for /f "delims=" %%v in ('"%PY%" --version 2^>^&1') do set "PYVER=%%v"
echo          [ok] %PYVER%
exit /b 0

:chk_python_old
for /f "delims=" %%v in ('"%PY%" --version 2^>^&1') do set "PYVER=%%v"
echo          [!!] TOO OLD: %PYVER%
call :usage_python
set /a FAILED+=1
exit /b 0

:chk_python_bad
echo          [!!] NOT FOUND
call :usage_python
set /a FAILED+=1
exit /b 0


rem ---------- [2] config.yaml ----------
:chk_config
echo   [2] The config file, config.yaml
if exist "%~dp0config.yaml" (
  echo          [ok] present
  exit /b 0
)
echo          [!!] NOT CONFIGURED - the file does not exist
echo               How to fix, in this folder:
echo                   copy config.example.yaml config.yaml
echo               macOS / Linux:
echo                   cp config.example.yaml config.yaml
echo               The default is sending.enabled: false, so nothing is sent
echo               until you deliberately turn it on.
echo               Docs: https://github.com/rainy-rain/Dy-spark/blob/main/README.md
set /a FAILED+=1
exit /b 0


rem ---------- [3] Playwright ----------
:chk_playwright
echo   [3] The Playwright package
if not defined PY goto :chk_playwright_bad
"%PY%" -c "import playwright" >nul 2>&1
if not errorlevel 1 (
  echo          [ok] installed
  exit /b 0
)
:chk_playwright_bad
echo          [!!] NOT CONFIGURED - not installed
echo               How to fix, in this folder:
echo                   .venv\Scripts\pip install -r requirements.txt
echo               macOS / Linux:
echo                   .venv/bin/pip install -r requirements.txt
echo               Docs: https://playwright.dev/python/docs/intro
set /a FAILED+=1
exit /b 0


rem ---------- [4] Edge / Chrome ----------
:chk_browser
echo   [4] Microsoft Edge or Google Chrome
set "BROWSER="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=Edge"
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=Edge"
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=Chrome"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER=Chrome"
if defined BROWSER (
  echo          [ok] %BROWSER% found
  exit /b 0
)
echo          [!!] NOT CONFIGURED - neither is installed
echo               How to fix, any one of these:
echo                 1. Install Microsoft Edge (quickest, and it saves dspark
echo                    from downloading 700MB of its own):
echo                       https://www.microsoft.com/edge
echo                 2. Install Google Chrome:
echo                       https://www.google.com/chrome/
echo                 3. Or let Playwright supply Chromium:
echo                       .venv\Scripts\python.exe -m playwright install chromium
set /a FAILED+=1
exit /b 0


rem ---------- [5] Playwright Chromium ----------
:chk_chromium
echo   [5] Playwright's own Chromium (only "login" needs it)
set "CHROMIUM="
if exist "%LOCALAPPDATA%\ms-playwright" (
  for /d %%d in ("%LOCALAPPDATA%\ms-playwright\chromium-*") do set "CHROMIUM=%%~nxd"
)
if exist "%~dp0.browsers" (
  for /d %%d in ("%~dp0.browsers\chromium-*") do set "CHROMIUM=%%~nxd"
)
if defined CHROMIUM (
  echo          [ok] installed: %CHROMIUM%
  exit /b 0
)
if defined BROWSER (
  echo          [ok] not installed, and not needed - %BROWSER% is enough
  echo               Only "python -m dspark login" would want it.
  exit /b 0
)
echo          [!!] NOT CONFIGURED - and no system browser either
echo               How to fix:
echo                   .venv\Scripts\python.exe -m playwright install chromium
echo               About 700MB, one time.
echo               Docs: https://playwright.dev/python/docs/intro
exit /b 0


rem ---------- [6] Douyin login ----------
:chk_login
echo   [6] Signed in to Douyin
if exist "%~dp0.session\storage_state.json" (
  echo          [ok] a saved session exists
  exit /b 0
)
if exist "%~dp0.edge-profile\Default" (
  echo          [ok] using a browser profile; the login lives inside it
  exit /b 0
)
echo          [!!] NOT CONFIGURED - never signed in
echo               Nothing to do right now. Step 2 opens a browser; in that
echo               window go to https://www.douyin.com/chat and sign in once
echo               with the Douyin app. It is remembered from then on.
exit /b 0


rem ---------- [7] Debug port ----------
:chk_port
echo   [7] Debug port %PORT%
netstat -an | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo          [ok] listening
  exit /b 0
)
echo          [!!] NOT CONFIGURED - nothing listening yet
echo               Nothing to do right now. Step 2 starts it.
echo               To start it by hand:
echo                   .venv\Scripts\python.exe -m dspark edge
exit /b 0


rem ---------- [8] Network ----------
:chk_network
echo   [8] Network access to douyin.com
set "NETOK=0"
where curl >nul 2>&1
if not errorlevel 1 (
  curl -s -o nul --max-time 8 https://www.douyin.com/ >nul 2>&1
  if not errorlevel 1 set "NETOK=1"
) else (
  ping -n 1 -w 3000 www.douyin.com >nul 2>&1
  if not errorlevel 1 set "NETOK=1"
)
if "%NETOK%"=="1" (
  echo          [ok] reachable
  exit /b 0
)
echo          [!!] NOT CONFIGURED - cannot reach it
echo               How to fix:
echo                 1. Check the internet connection.
echo                 2. If a proxy or VPN is running, make sure it covers this
echo                    program too - a browser-only proxy does not.
echo                 3. Try opening https://www.douyin.com/ in your browser.
set /a FAILED+=1
exit /b 0


rem ---------- tutorial: Python ----------
:usage_python
echo               How to fix, any one of these:
echo                 1. Install with winget:
echo                       winget install Python.Python.3.12
echo                 2. Or download the installer:
echo                       https://www.python.org/downloads/
echo                    Tick "Add python.exe to PATH" during the install.
echo                 3. Reopen this window, then:
echo                       python -m venv .venv
echo                       .venv\Scripts\pip install -r requirements.txt
echo               Docs: https://github.com/rainy-rain/Dy-spark/blob/main/README.md
exit /b 0
