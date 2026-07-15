# Asgard installer — Windows PowerShell entry point (CUS-222). install.sh 의 흐름과 동일:
# uv 부트스트랩 → standalone CPython 3.14 → `uv tool install asgard`. 시스템 Python/Node/git 불요.
#   irm https://raw.githubusercontent.com/CustomJH/asgard-custom/main/install.ps1 | iex
# Env: ASGARD_VERSION (pin X.Y.Z) · ASGARD_INSTALL_SPEC (override source)
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$RepoSlug = 'CustomJH/asgard-custom'

function Write-Ok   ($msg) { Write-Host "  " -NoNewline; Write-Host "OK " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Write-Info ($msg) { Write-Host "   . $msg" -ForegroundColor DarkGray }
function Write-Warn2($msg) { Write-Host "  " -NoNewline; Write-Host "!  " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Fail ($msg) { Write-Host ""; Write-Host "  X  $msg" -ForegroundColor Red; exit 1 }

$script:Step = 0
function Phase ($title) {
    $script:Step++
    Write-Host ""
    Write-Host "  [$script:Step/3] " -ForegroundColor Cyan -NoNewline
    Write-Host $title -ForegroundColor White
}

function Get-LatestVersion {
    # /releases/latest 리다이렉트로 최신 태그 해석 (vX.Y.Z → X.Y.Z) — API 토큰·git 불요.
    try {
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$RepoSlug/releases/latest" -TimeoutSec 15
        if ($rel.tag_name -match '^v?([0-9][0-9.]*)$') { return $Matches[1] }
    } catch { }
    return $null
}

function Main {
    Write-Host ""
    Write-Host "  ASGARD" -ForegroundColor White
    Write-Host "  make anything, your way" -ForegroundColor DarkGray

    # ── [1/3] preflight ──
    Phase "preflight - check environment"
    $haveUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)
    if ($haveUv) { Write-Ok ("uv " + (uv --version 2>$null) + " (already installed)") }
    else { Write-Info "uv absent - will bootstrap in step 2" }

    # ── [2/3] install ──
    Phase "install - toolchain + asgard"
    if (-not $haveUv) {
        try { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression }
        catch { Fail "uv install failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/" }
        # uv 설치 스크립트는 %USERPROFILE%\.local\bin 에 놓고 영구 PATH 는 새 셸부터 반영 — 이 세션엔 직접 주입.
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Fail "uv not on PATH - restart the terminal and re-run." }
        Write-Ok ("uv " + (uv --version 2>$null))
    }
    uv python install 3.14 2>$null | Out-Null
    Write-Ok "python 3.14"

    if ($env:ASGARD_INSTALL_SPEC) {
        $from = $env:ASGARD_INSTALL_SPEC; $desc = 'custom spec'
    } else {
        $v = $env:ASGARD_VERSION
        if (-not $v) { $v = Get-LatestVersion }
        if (-not $v) { Fail "could not resolve a version to install (network down?). Set ASGARD_VERSION=X.Y.Z and retry." }
        $from = "https://github.com/$RepoSlug/releases/download/v$v/asgard-$v-py3-none-any.whl"
        $desc = "v$v wheel"
    }
    Write-Info "installing asgard ($desc)..."
    uv tool install --force --python 3.14 $from
    if ($LASTEXITCODE -ne 0) { Fail "install failed: $from" }
    uv tool update-shell 2>$null | Out-Null
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    Write-Ok "asgard linked (uv tool)"

    # ── [3/3] verify ──
    Phase "verify - check install"
    $ver = try { asgard --version 2>$null } catch { '?' }
    Write-Ok "asgard v$ver"
    $cmd = Get-Command asgard -ErrorAction SilentlyContinue
    if ($cmd) { Write-Ok "on PATH $($cmd.Source)" }
    else { Write-Warn2 "not on PATH yet - restart the terminal (or run: uv tool update-shell)" }

    Write-Host ""
    Write-Host "  installed" -ForegroundColor Green -NoNewline; Write-Host " - next:"
    Write-Host "    asgard doctor   " -NoNewline; Write-Host "# verify" -ForegroundColor DarkGray
    Write-Host "    asgard --help"
    Write-Host ""
}

Main
