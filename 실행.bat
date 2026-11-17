@echo off
chcp 65001 >nul
rem MES 검색 실험실 실행 파일: 더블클릭하면 서버를 켜고 브라우저를 엽니다.
cd /d "%~dp0"

rem Python 3.9 이상 찾기 (python -> py 순서). Microsoft Store 바로가기(python.exe)는 실행에 실패하므로 걸러짐.
set "PY="
python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul && set "PY=python"
if not defined PY py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul && set "PY=py -3"
if not defined PY (
  echo [오류] Python 3.9 이상이 필요합니다.
  echo https://www.python.org/downloads/ 에서 설치하세요.
  echo 설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
  echo.
  pause
  exit /b 1
)

echo MES 검색 실험실을 시작합니다. 잠시 후 브라우저가 열립니다.
echo 이 창을 닫으면 서버가 종료됩니다.
echo.
%PY% app.py --open
echo.
pause
