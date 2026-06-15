<#
  ArchiveCheck - guided installer (Windows)

  Installs the Python dependencies and the external tools the checker needs, then
  prints a capability report. Re-runnable: it skips what is already present.

  Usage (from the repo folder):
      powershell -ExecutionPolicy Bypass -File .\install.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

Write-Host "=== ArchiveCheck installer ===" -ForegroundColor Cyan

# --- 1. Python check ------------------------------------------------------- #
if (-not (Have "py") -and -not (Have "python")) {
    Write-Host "Python 3.10+ not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH') and re-run." -ForegroundColor Red
    exit 1
}
$py = if (Have "py") { "py" } else { "python" }

# --- 2. Python dependencies ----------------------------------------------- #
Write-Host "`n[1/4] Installing Python dependencies (this includes TensorFlow; large)..." -ForegroundColor Cyan
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt

# --- 3. External binaries via winget -------------------------------------- #
Write-Host "`n[2/4] Checking external tools..." -ForegroundColor Cyan
if (Have "winget") {
    if (-not (Have "ffmpeg")) {
        Write-Host "  installing ffmpeg..."
        winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    } else { Write-Host "  ffmpeg: already installed" }
    if (-not (Have "tesseract")) {
        Write-Host "  installing tesseract..."
        winget install -e --id UB-Mannheim.TesseractOCR --accept-source-agreements --accept-package-agreements
    } else { Write-Host "  tesseract: already installed" }
} else {
    Write-Host "  winget not available - install ffmpeg and tesseract manually (see README)." -ForegroundColor Yellow
}

# --- .env (create early so later steps can append keys/paths) ------------- #
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "  created .env from .env.example"
}

# --- 3b. Swedish OCR language data ---------------------------------------- #
Write-Host "`n[3b/4] Setting up Swedish OCR language (credits are in Swedish)..." -ForegroundColor Cyan
$tessExe = (Get-Command tesseract -ErrorAction SilentlyContinue).Source
if ($tessExe) {
    $sysTd = Join-Path (Split-Path $tessExe) "tessdata"
    $sweUrl = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/swe.traineddata"
    $haveSwe = ((& tesseract --list-langs 2>&1) -join "`n") -match '(?m)^\s*swe\s*$'
    if ($haveSwe) {
        Write-Host "  Swedish (swe) already installed"
    } else {
        try {
            Invoke-WebRequest $sweUrl -OutFile (Join-Path $sysTd "swe.traineddata") -UseBasicParsing
            Write-Host "  installed swe.traineddata to $sysTd"
        } catch {
            # No write access to the install dir - use a local tessdata + env var.
            $localTd = Join-Path $PSScriptRoot "tessdata"
            New-Item -ItemType Directory -Force -Path $localTd | Out-Null
            Copy-Item (Join-Path $sysTd "eng.traineddata") $localTd -ErrorAction SilentlyContinue
            Copy-Item (Join-Path $sysTd "osd.traineddata") $localTd -ErrorAction SilentlyContinue
            Copy-Item (Join-Path $sysTd "configs") $localTd -Recurse -Force -ErrorAction SilentlyContinue
            try { Invoke-WebRequest $sweUrl -OutFile (Join-Path $localTd "swe.traineddata") -UseBasicParsing } catch {}
            if ((Test-Path ".env") -and ((Get-Content ".env" -Raw) -notmatch '(?m)^\s*TESSDATA_PREFIX')) {
                Add-Content ".env" "`nTESSDATA_PREFIX=$localTd"
            }
            Write-Host "  installed Swedish to local $localTd (TESSDATA_PREFIX set in .env)" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  tesseract not found yet; re-run after it's on PATH to add Swedish." -ForegroundColor Yellow
}

# --- 4. fpcalc (Chromaprint) best-effort ---------------------------------- #
Write-Host "`n[3/4] Setting up fpcalc (Chromaprint, optional - for song identification)..." -ForegroundColor Cyan
$fpcalcExe = ""
if (Have "fpcalc") {
    $fpcalcExe = (Get-Command fpcalc).Source
    Write-Host "  fpcalc: already on PATH"
} else {
    try {
        $ver = "1.5.1"
        $url = "https://github.com/acoustid/chromaprint/releases/download/v$ver/chromaprint-fpcalc-$ver-windows-x86_64.zip"
        $zip = Join-Path $env:TEMP "fpcalc.zip"
        $tools = Join-Path $PSScriptRoot "tools"
        New-Item -ItemType Directory -Force -Path $tools | Out-Null
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $tools -Force
        Remove-Item $zip -Force
        $found = Get-ChildItem -Path $tools -Recurse -Filter fpcalc.exe | Select-Object -First 1
        if ($found) { $fpcalcExe = $found.FullName; Write-Host "  fpcalc installed to $fpcalcExe" }
    } catch {
        Write-Host "  Could not auto-download fpcalc (optional). You can add it later; see README." -ForegroundColor Yellow
    }
}

# --- 5. .env (record fpcalc path) ----------------------------------------- #
Write-Host "`n[4/4] Finalising .env..." -ForegroundColor Cyan
if ($fpcalcExe -and (Test-Path ".env")) {
    $envText = Get-Content ".env" -Raw
    if ($envText -notmatch '(?m)^\s*FPCALC\s*=\s*\S') {
        Add-Content ".env" "`nFPCALC=$fpcalcExe"
        Write-Host "  wrote FPCALC path to .env"
    }
}

# Refresh PATH for this session so --check sees freshly installed tools.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

Write-Host "`n=== Done. Capability check: ===" -ForegroundColor Green
& $py -m archivecheck --check
Write-Host "`nTip: add your free ACOUSTID_API_KEY (and optional ANTHROPIC_API_KEY) to .env." -ForegroundColor Cyan
Write-Host "If tools show as NOT FOUND, close and reopen the terminal so PATH refreshes." -ForegroundColor Yellow
