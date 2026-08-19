# Asgard 환경 프리플라이트 (Windows) — 훅이 부를 파이썬이 이 기계에 있는지 보고, 없으면 세운다.
#
# POSIX 쪽 쌍둥이는 `env-setup.sh` 이고 뜻이 같다. 러너만 다르다: Windows 에는 `sh` 가 있다는
# 보장이 없고 PowerShell 은 어느 판에나 실려 있다. 배선은 스캐폴드 시점에 갈려서, 한 기계에는
# 프리플라이트 줄이 하나만 선다 (`platform.py` 의 `preflight_command` 가 러너를 고른다).
#
#   powershell -File env-setup.ps1 <claude-code|codex|cursor>   배선된 런타임이 서는지 본다
#   powershell -File env-setup.ps1 -Install                     uv 와 CPython 3.14 을 깐다
#
# 판정만 하고 아무것도 막지 않는다 — 판정 갈래는 언제나 exit 0 이다.
[CmdletBinding()]
param(
  [Parameter(Position = 0)][string]$Client = 'claude-code',
  [switch]$Install
)

$ProgressPreference = 'SilentlyContinue'
$PIN = '3.14'
$WIRING = @('.claude/settings.json', '.codex/config.toml', '.cursor/hooks.json')
$MARK = ' run --no-project python'

# 저장소 뿌리 — 이 파일은 `<뿌리>\<호스트>\hooks\` 에 깔리므로 두 칸 올라가면 뿌리다. 호스트가
# 주는 환경 변수와 현재 위치를 뒤 후보로 두고, 배선 파일이 보이는 첫 자리에 선다.
function Find-Root {
  $candidates = @()
  if ($PSScriptRoot) { $candidates += (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) }
  if ($env:CLAUDE_PROJECT_DIR) { $candidates += $env:CLAUDE_PROJECT_DIR }
  $candidates += (Get-Location).Path
  foreach ($c in $candidates) {
    if (-not $c) { continue }
    foreach ($w in $WIRING) {
      if (Test-Path -LiteralPath (Join-Path $c $w) -PathType Leaf) { return $c }
    }
  }
  return $null
}

# 배선 줄이 부르는 인터프리터의 첫 낱말. `command` 를 함께 요구하는 이유는 권한 허용목록이다 —
# 거기에도 `Bash(uv run --no-project python ...)` 가 있고 파일 앞쪽이라, 문구만 보면 인터프리터가
# `Bash(uv` 로 읽힌다. 마지막 따옴표(또는 그 앞의 역슬래시) 뒤부터가 프로그램 경로다.
function Get-WiredToken([string]$Path) {
  foreach ($line in [System.IO.File]::ReadLines($Path)) {
    if ($line -notmatch 'command') { continue }
    $at = $line.IndexOf($MARK)
    if ($at -lt 0) { continue }
    $head = $line.Substring(0, $at)
    $cut = [Math]::Max([Math]::Max($head.LastIndexOf('"'), $head.LastIndexOf("'")), $head.LastIndexOf('\'))
    return $head.Substring($cut + 1)
  }
  return ''
}

function Test-Runnable([string]$Token) {
  if (-not $Token) { return $false }
  if ($Token -match '[\\/]') { return (Test-Path -LiteralPath $Token -PathType Leaf) }
  return [bool](Get-Command $Token -ErrorAction SilentlyContinue)
}

# uv 찾는 차례 — PATH 를 먼저 보고, 없으면 설치기들이 쓰는 자리를 밟는다. POSIX 쪽 `uv_path` 와
# 같은 뜻이고 자리 목록만 Windows 것이다 (애스트랄 설치기, cargo, winget 의 링크 폴더).
function Find-Uv {
  $cmd = Get-Command uv -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $spots = @()
  if ($env:USERPROFILE) {
    $spots += (Join-Path $env:USERPROFILE '.local\bin\uv.exe')
    $spots += (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
  }
  if ($env:LOCALAPPDATA) { $spots += (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe') }
  foreach ($s in $spots) { if (Test-Path -LiteralPath $s -PathType Leaf) { return $s } }
  return ''
}

# 방금 깐 uv 는 이 프로세스가 뜰 때 없던 폴더에 있다 — 레지스트리의 PATH 를 다시 읽어야 잡힌다.
function Update-PathFromEnvironment {
  try {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $joined = @($machine, $user) | Where-Object { $_ }
    if ($joined) { $env:Path = ($joined -join ';') }
  } catch { }
}

function Write-Offer([string]$Text) {
  if ($Client -eq 'cursor') {
    # Cursor 의 컨텍스트 통로는 이 키 하나다 (asgard_hooklib/inject.py 와 같은 규약).
    ConvertTo-Json -Compress -InputObject @{ additional_context = $Text }
  } else {
    $Text
  }
}

$root = Find-Root
if (-not $root) { exit 0 }
Set-Location -LiteralPath $root

if (-not $Install) {
  $broken = ''
  $found = $false
  foreach ($w in $WIRING) {
    $p = Join-Path $root $w
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { continue }
    $token = Get-WiredToken $p
    if (-not $token) { continue }
    $found = $true
    if (-not (Test-Runnable $token)) { $broken = $token; break }
  }
  if (-not $found) {
    # POSIX 기계에서 만들어진 배선은 인터프리터 대신 sh 런처를 부른다 — 그 줄은 위 추출에 안
    # 걸리고 여기서는 어차피 못 돈다. 그래도 uv 나 python 이 있으면 훅은 설 수 있으므로 물음을
    # 런타임 존재로 되돌린다.
    foreach ($c in @('uv', 'python', 'py')) {
      if (Get-Command $c -ErrorAction SilentlyContinue) { exit 0 }
    }
    $broken = 'uv'
  }
  if (-not $broken) { exit 0 }

  Write-Offer @"
[asgard] 이 저장소의 훅을 돌릴 파이썬이 이 기계에 없어요.
배선이 부르는 자리는 ``$broken`` 인데 거기가 비어 있어요. 훅은 실패해도 세션을 막지 않아서,
지금 이 세션은 가드·기억 주입·퀘스트 게이트가 전부 꺼진 채로 돌고 있어요.

세우는 명령 — uv 와 CPython $PIN 를 깔고, 훅 배선을 이 기계의 uv 자리로 다시 써요:
    powershell -NoProfile -ExecutionPolicy Bypass -File "$PSCommandPath" -Install

이 문단을 사용자에게 그대로 전하고, 설치해도 되는지 물어본 뒤에 실행하세요.
"@
  exit 0
}

Write-Output "[asgard] 환경을 세워요 - uv, CPython $PIN, 훅 배선."

$uv = Find-Uv
if (-not $uv) {
  # 애스트랄 설치 스크립트는 자식 PowerShell 에서 돌린다 — 남의 스크립트가 이 세션의
  # ErrorActionPreference·PATH·모듈 상태를 건드리지 않게 한다 (install.ps1 도 같은 이유).
  $ps = Get-Command powershell -ErrorAction SilentlyContinue
  if (-not $ps) { $ps = Get-Command pwsh -ErrorAction SilentlyContinue }
  if ($ps) {
    $inner = '$ErrorActionPreference = "Stop";' +
      '$ProgressPreference = "SilentlyContinue";' +
      '[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12;' +
      'Invoke-RestMethod https://astral.sh/uv/install.ps1 -UseBasicParsing | Invoke-Expression'
    $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
    & $ps.Source '-NoProfile' '-ExecutionPolicy' 'Bypass' '-NonInteractive' '-EncodedCommand' $enc | Out-Null
    Update-PathFromEnvironment
    $uv = Find-Uv
  }
}
if (-not $uv -and (Get-Command winget -ErrorAction SilentlyContinue)) {
  & winget install --id astral-sh.uv -e --source winget --accept-package-agreements --accept-source-agreements | Out-Null
  Update-PathFromEnvironment
  $uv = Find-Uv
}
if (-not $uv) {
  foreach ($py in @('py', 'python', 'python3')) {
    if (-not (Get-Command $py -ErrorAction SilentlyContinue)) { continue }
    $pipArgs = @('-m', 'pip', 'install', '--user', '--upgrade', 'uv')
    if ($py -eq 'py') { $pipArgs = @('-3') + $pipArgs }
    & $py @pipArgs | Out-Null
    Update-PathFromEnvironment
    $uv = Find-Uv
    if ($uv) { break }
  }
}
if (-not $uv) {
  Write-Error '[asgard] uv 를 못 깔았어요. 손으로 깔고 다시 실행해 주세요 - https://docs.astral.sh/uv/getting-started/installation/'
  exit 1
}
Write-Output "  uv      $uv"

& $uv python install $PIN 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
  Write-Output "  python  $PIN"
} else {
  Write-Output "  python  $PIN - 미리 받기는 건너뛰었어요 (uv 가 처음 쓸 때 받아요)"
}

$changed = $false
foreach ($w in $WIRING) {
  $p = Join-Path $root $w
  if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { continue }
  $old = Get-WiredToken $p
  if (-not $old -or $old -eq $uv) { continue }
  # 맨 토큰 배선(`uv ...`)은 PATH 가 푸는 값이라 다시 쓸 자리가 없다 — uv 를 깐 것만으로 이미
  # 고쳐졌다. 그런데 아래 치환은 파일 전체를 훑으므로, `old` 가 두 글자 `uv` 면 권한 허용목록의
  # `Bash(uv run --no-project python ...)` 까지 절대 경로로 바뀌고, 모델이 안내문대로 친 명령이
  # 헤드리스에서 자동 거부된다. 경로가 아니면 건너뛴다.
  if ($old -notmatch '[\\/]') { continue }
  $text = [System.IO.File]::ReadAllText($p)
  [System.IO.File]::WriteAllText($p, $text.Replace($old, $uv))
  $changed = $true
  Write-Output "  배선    $w"
}
if ($changed) {
  Write-Output '  배선 파일은 기계마다 값이 달라요 - 이 변경은 이 기계 것이라 커밋하지 않는 편이 좋아요.'
} else {
  Write-Output '  배선    고쳐 쓸 자리가 없어요 - 배선이 이미 이 기계에서 uv 를 찾아요'
}

& $uv run --no-project python -c pass 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
  Write-Output "[asgard] 훅이 서요 - $uv run --no-project python"
  Write-Output '         새 세션부터 적용돼요. 이 세션은 한 번 다시 열어 주세요.'
} else {
  Write-Error "[asgard] 아직 안 서요. 새 터미널을 열고 다시 실행해 주세요 - powershell -File `"$PSCommandPath`" -Install"
  exit 1
}
