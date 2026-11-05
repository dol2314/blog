@echo off
chcp 65001 >nul
cd /d "%~dp0"
title TubeForge - AI 쇼츠 만들기
where python >/dev/null 2>/dev/null || (echo Python 3.10 이상을 python.org 에서 설치하세요 ^(설치 때 Add to PATH 체크^). & pause & exit /b 1)
if not exist .venv (
  echo [준비] 가상환경 만드는 중...
  python -m venv .venv || (pause & exit /b 1)
  .venv\Scripts\python -m pip install -q --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
)
if not exist .env copy .env.example .env >nul
set /p TOPIC=영상 주제를 입력하세요: 
set /p VTYPE=형식 (shorts / long, 그냥 Enter = shorts): 
if "%VTYPE%"=="" set VTYPE=shorts
.venv\Scripts\python main.py --topic "%TOPIC%" --type %VTYPE%
echo.
echo output 폴더를 엽니다.
start "" output
pause
