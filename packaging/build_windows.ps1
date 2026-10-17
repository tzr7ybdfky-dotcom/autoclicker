# Сборка AutoClicker.exe на Windows x64 (собирать нужно на Windows).
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#
# Нужен 64-битный Python 3.12 (python.org). Интерпретатор можно указать:
#   $env:PYTHON = "C:\Python312\python.exe"
# Флаг -ExecutionPolicy Bypass действует только на этот запуск и не меняет
# политику системы.
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$Python = if ($env:PYTHON) { $env:PYTHON } else { "py" }
$PyArgs = if ($env:PYTHON) { @() } else { @("-3.12") }
$Venv = "build\venv-windows"

function Run($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Команда завершилась с ошибкой: $exe $arguments" }
}

Write-Host "==> Виртуальное окружение: $Venv"
Run $Python ($PyArgs + @("-m", "venv", $Venv))
$VPy = Join-Path $Venv "Scripts\python.exe"
Run $VPy @("-c", "import struct, sys; assert struct.calcsize('P') == 8, 'нужен 64-битный Python'; print(sys.version)")
Run $VPy @("-m", "pip", "install", "--upgrade", "pip")
Run $VPy @("-m", "pip", "install", "-r", "requirements-dev.txt")

Write-Host "==> Тесты (без реальных кликов)"
Run $VPy @("-m", "pytest")

Write-Host "==> Иконка"
Run $VPy @("packaging\make_icons.py")

Write-Host "==> PyInstaller"
if (Test-Path "dist\AutoClicker") { Remove-Item -Recurse -Force "dist\AutoClicker" }
Run $VPy @("-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", "dist", "--workpath", "build\pyinstaller", "packaging\autoclicker.spec")

Write-Host "==> Проверка сборки (--smoke-test, без кликов)"
$Exe = Join-Path $Root "dist\AutoClicker\AutoClicker.exe"
$p = Start-Process -FilePath $Exe -ArgumentList "--smoke-test" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Smoke-тест сборки не прошёл (код $($p.ExitCode))" }
Write-Host "Готово: $Exe (раздавайте всю папку dist\AutoClicker)"
