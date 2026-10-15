@echo off
chcp 65001 >nul
rem 문제를 찾을 때 쓰는 실행 파일: 검은 창에 진행 기록이 보이고, 창이 닫히지 않는다.
call "%~dp0실행.bat" debug
