@echo off
set EXCEL=%~1
if "%EXCEL%"=="" set EXCEL=collection.xlsx
python scripts\build_all.py --excel "%EXCEL%"
pause
