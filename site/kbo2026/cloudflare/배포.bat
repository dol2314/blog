@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 2026 프로야구 일정 중계 - Cloudflare 배포
where npx >nul 2>nul
if errorlevel 1 (
  echo Node.js 가 설치되어 있지 않습니다.
  echo https://nodejs.org 에서 LTS 버전을 설치한 뒤 다시 실행하세요.
  pause
  exit /b 1
)
echo [1/2] Cloudflare 로그인 (브라우저가 열리면 허용을 누르세요)
call npx -y wrangler@4 login
echo.
echo [2/2] 업로드 중...
call npx -y wrangler@4 pages deploy . --project-name kbo2026 --branch main --commit-dirty=true
echo.
echo 위에 나온 https://....pages.dev 주소가 사이트 주소입니다.
pause
