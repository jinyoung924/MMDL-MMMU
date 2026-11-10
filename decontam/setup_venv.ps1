# Creates .venv (git-ignored) for decontam/quick_check.py and runs the offline test.
#   VS Code: Terminal > Run Task > "decontam: 1) 가상환경 만들기"
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "== .venv 만드는 중 (Python 3.11) =="
    if (Test-Path $py) { & $py -m venv .venv } else { & py -3.11 -m venv .venv }
}
$vpy = ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet
Write-Host "== 패키지 설치 =="
& $vpy -m pip install -r decontam\requirements-quick.txt --quiet
Write-Host "== 오프라인 테스트 =="
$env:PYTHONUTF8 = "1"
& $vpy decontam\tests\test_quick.py
& $vpy decontam\tests\test_local.py
Write-Host "준비 끝. 다음: Run Task > decontam: 2) 간이 검사 실행"
