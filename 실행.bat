@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title 블로그 자동 업로드

echo ============================================
echo   블로그 자동 업로드 프로그램
echo ============================================
echo.

if exist ".venv\Scripts\python.exe" goto install

rem ---- 1. 파이썬 찾기 ----
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if defined PY goto make_venv
python --version >nul 2>&1 && set "PY=python"
if defined PY goto make_venv
echo [오류] 파이썬이 설치되어 있지 않습니다.
echo https://www.python.org/downloads/ 에서 설치해 주세요.
echo 설치 첫 화면의 "Add python.exe to PATH"를 꼭 체크하세요.
echo.
pause
exit /b 1

:make_venv
echo [1/3] 프로그램 전용 파이썬 환경을 만드는 중...
%PY% -m venv .venv
if errorlevel 1 goto fail

rem ---- 2. 부품 설치 - requirements.txt가 바뀌었을 때만 다시 설치 ----
:install
set "VPY=.venv\Scripts\python.exe"
fc /b requirements.txt .venv\requirements.installed >nul 2>&1
if not errorlevel 1 goto browser
echo [2/3] 필요한 부품을 설치하는 중... 처음 한 번만 몇 분 걸립니다.
"%VPY%" -m pip install --upgrade pip >nul 2>&1
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail
copy /y requirements.txt .venv\requirements.installed >nul

rem ---- 3. 브라우저 - 크롬이 있으면 크롬을 쓰고, 없으면 내려받기 ----
:browser
if exist ".venv\browser.installed" goto apikey
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" goto browser_done
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" goto browser_done
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" goto browser_done
echo [3/3] 크롬이 없어 프로그램용 브라우저를 내려받는 중...
"%VPY%" -m playwright install chromium
if errorlevel 1 goto fail
:browser_done
echo ok> .venv\browser.installed

rem ---- 4. Claude API 키 - AI 글쓰기에만 필요 ----
:apikey
if defined ANTHROPIC_API_KEY goto run
if exist api_key.txt set /p ANTHROPIC_API_KEY=<api_key.txt
if defined ANTHROPIC_API_KEY goto run
echo.
echo AI 글쓰기를 쓰려면 Claude API 키가 필요합니다: https://console.anthropic.com
echo 키가 없으면 그냥 Enter를 누르세요. 내가 쓴 파일 올리기는 키 없이 됩니다.
set /p "ANTHROPIC_API_KEY=API 키: "
if not defined ANTHROPIC_API_KEY goto run
echo %ANTHROPIC_API_KEY%> api_key.txt
echo 키를 api_key.txt에 저장했습니다. 다음부터는 묻지 않습니다.

:run
echo.
"%VPY%" -m autoposter %*
echo.
pause
exit /b

:fail
echo.
echo [오류] 설치 중 문제가 생겼습니다. 위 메시지를 캡처해서 알려 주세요.
echo.
pause
exit /b 1
