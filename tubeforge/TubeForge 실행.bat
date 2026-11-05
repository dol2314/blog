@echo off
chcp 65001 >nul
setlocal
set "APP=%~dp0"
pushd "%APP%" >nul 2>&1
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title TubeForge

echo ============================================
echo   TubeForge - AI 유튜브 영상 제작 앱
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
echo [1/2] 프로그램 전용 파이썬 환경을 만드는 중...
%PY% -m venv .venv
if errorlevel 1 goto fail

rem ---- 2. 부품 설치 - requirements.txt가 바뀌었을 때만 다시 설치 ----
:install
set "VPY=.venv\Scripts\python.exe"
fc /b "%APP%requirements.txt" .venv\requirements.installed >nul 2>&1
if not errorlevel 1 goto run
echo [2/2] 필요한 부품을 설치하는 중... 처음 한 번만 몇 분 걸립니다.
"%VPY%" -m pip install --upgrade pip >nul 2>&1
"%VPY%" -m pip install -r "%APP%requirements.txt"
if errorlevel 1 goto fail
copy /y "%APP%requirements.txt" .venv\requirements.installed >nul

:run
if not exist ".env" copy /y ".env.example" ".env" >nul
echo 앱 창을 여는 중입니다. 이 검은 창은 닫지 말고 그대로 두세요.
echo.
"%VPY%" -m app
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo [오류] 위에 나온 메시지를 캡처해서 보내 주세요.
pause
exit /b 1
