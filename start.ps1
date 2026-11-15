Set-Location $PSScriptRoot
& "$PSScriptRoot/.venv/Scripts/python.exe" -m flask --app app run --debug
