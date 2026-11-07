# Start MangaPlay: http://127.0.0.1:8000
# Builds the web app the first time, then runs the backend (which also serves the app and runs the queue).
Set-Location $PSScriptRoot
if (-not (Test-Path "app\dist\index.html")) {
    Push-Location app
    pnpm install
    pnpm build
    Pop-Location
}
& .\.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000
