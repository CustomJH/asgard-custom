# Asgard installer - Windows PowerShell entry point. Same flow as install.sh:
# uv bootstrap -> standalone CPython 3.14 -> `uv tool install asgard`. No system Python/Node/git.
#   irm https://raw.githubusercontent.com/CustomJH/asgard-custom/main/install.ps1 | iex
# Env: ASGARD_VERSION (pin X.Y.Z) - ASGARD_INSTALL_SPEC (override source) - ASGARD_NO_PAUSE=1 - NO_COLOR
#
# This file is deliberately ASCII-only and Windows PowerShell 5.1 syntax-only. It is fetched as text
# and run through Invoke-Expression, so one PS7-only operator or one mis-decoded byte would take the
# whole script down at parse time - before any handler inside it could say why.
#
# Three rules keep a failure readable instead of closing the user's terminal:
#   1. Nothing in this session calls `exit` while work is in flight. Under `irm | iex` an `exit`
#      terminates the HOST shell, so a failed step used to make the window vanish with no message.
#      Failures throw and land in the single handler at the bottom, which holds the window open.
#   2. Foreign bootstrap scripts (astral.sh/uv/install.ps1) run in a CHILD powershell. Verified
#      26-07-27: its last four lines are `catch { Write-Information $_; exit 1 }`. Piped into this
#      session, that `exit` closes the window a split second after printing the reason - which is
#      what "it just flashes and disappears" is. In a child it only ends the child, and we keep the
#      output. It also stops its `$InformationPreference = "Continue"` from leaking into the shell.
#   3. Native commands never get their stderr redirected while $ErrorActionPreference is 'Stop'.
#      Windows PowerShell turns redirected native stderr into terminating NativeCommandErrors; the
#      old `uv ... 2>$null` lines could abort the script on a step that had actually succeeded.
#Requires -Version 5.1
# Under `irm | iex` these assignments land in the USER's live session, not in a script scope of our
# own - so both are put back at the bottom. Leaving 'Stop' behind would turn every later non-fatal
# error in their shell into a terminating one.
$script:AsgardPrevEap = $ErrorActionPreference
$script:AsgardPrevProgress = $ProgressPreference
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # the IWR progress bar is slow and noisy in conhost

$AsgardRepoSlug = 'CustomJH/asgard-custom'
$AsgardFailMark = 'ASGARD_FAIL::'

$script:AsgardLog = New-Object System.Collections.ArrayList
$script:AsgardHints = New-Object System.Collections.ArrayList
$script:AsgardStep = 0
$script:AsgardUseColor = -not $env:NO_COLOR

# -- output - every line also lands in the transcript we can write out on failure ---------------
function Add-Log ($text) { [void]$script:AsgardLog.Add([string]$text) }
function Add-Hint ($text) { [void]$script:AsgardHints.Add([string]$text) }

function Tint ($text, $color, [switch]$NoNewline) {
    if ($script:AsgardUseColor -and $color) { Write-Host $text -ForegroundColor $color -NoNewline:$NoNewline }
    else { Write-Host $text -NoNewline:$NoNewline }
}

function Write-Ok ($msg) {
    Add-Log ("  OK  " + $msg)
    Write-Host "  " -NoNewline; Tint "OK " 'Green' -NoNewline; Write-Host $msg
}
function Write-Info ($msg) { Add-Log ("   .  " + $msg); Tint ("   . " + $msg) 'DarkGray' }
function Write-Warn2 ($msg) {
    Add-Log ("  !   " + $msg)
    Write-Host "  " -NoNewline; Tint "!  " 'Yellow' -NoNewline; Write-Host $msg
}
function Write-Trace ($msg) { Add-Log ("      | " + $msg); Tint ("      | " + $msg) 'DarkGray' }

# Fail <msg> - expected, explained failure. Throws instead of exiting so the terminal survives long
# enough to show the reason; the marker tells the bottom handler this is a message, not a crash.
function Fail ($msg) { throw ($AsgardFailMark + $msg) }

function Phase ($title) {
    $script:AsgardStep++
    Write-Host ""
    Add-Log ("[" + $script:AsgardStep + "/3] " + $title)
    Tint ("  [" + $script:AsgardStep + "/3] ") 'Cyan' -NoNewline
    Tint $title 'White'
}

# -- process helpers ---------------------------------------------------------------------------
function Test-Cmd ($name) {
    $c = Get-Command $name -ErrorAction SilentlyContinue
    if ($c) { return $true }
    return $false
}

# Invoke-Native <file> <args> - run an executable and report by exit code, never by exception.
# $ErrorActionPreference is forced to 'Continue' for the call: with 'Stop' in effect, Windows
# PowerShell converts a native command's redirected stderr into a terminating NativeCommandError,
# and tools like uv write ordinary progress there. Returns @{ Code; Output }.
function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [string[]]$Arguments = @(),
        [switch]$Quiet
    )
    if (-not (Test-Cmd $File)) {
        $miss = "'" + $File + "' not found on PATH"
        Add-Log ("      | " + $miss)
        return (New-Object psobject -Property @{ Code = 9009; Output = $miss })
    }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    # PowerShell 7.3+ can promote a non-zero native exit into a terminating error on its own - the
    # modern shape of the same trap, and it ignores $ErrorActionPreference alone. Only touched when
    # the variable exists, so Windows PowerShell 5.1 walks straight past this.
    $hasNativePref = [bool](Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue)
    if ($hasNativePref) { $PSNativeCommandUseErrorActionPreference = $false }
    $lines = New-Object System.Collections.ArrayList
    $code = 0
    try {
        $global:LASTEXITCODE = 0
        & $File @Arguments 2>&1 | ForEach-Object {
            $line = ''
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $line = $_.ToString() } else { $line = [string]$_ }
            if ($Quiet) { Add-Log ("      | " + $line) } else { Write-Trace $line }
            [void]$lines.Add($line)
        }
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
    } catch {
        $msg = $_.Exception.Message
        [void]$lines.Add($msg)
        Add-Log ("      | " + $msg)
        $code = 9009
    } finally {
        $ErrorActionPreference = $prev
    }
    return (New-Object psobject -Property @{ Code = $code; Output = ($lines -join [Environment]::NewLine) })
}

function Get-PowerShellExe {
    $candidates = @()
    if ($PSVersionTable.PSEdition -eq 'Core') { $candidates += 'pwsh.exe' }
    $candidates += 'powershell.exe'
    foreach ($c in $candidates) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

# Update-PathFromEnvironment - a just-installed uv lands in a directory that only exists on the
# PERSISTED path; this process still holds the PATH it was born with. Re-read Machine+User and
# re-add the two directories uv is known to use, so the next call finds it without a new terminal.
function Update-PathFromEnvironment {
    # Strictly additive, and the live PATH stays in front: under `irm | iex` this edits the user's own
    # session, so reordering what they already had could shadow a venv or a pinned toolchain.
    $parts = New-Object System.Collections.ArrayList
    if ($env:Path) { foreach ($p in $env:Path.Split(';')) { if ($p) { [void]$parts.Add($p) } } }
    foreach ($scope in @('Machine', 'User')) {
        $v = ''
        try { $v = [Environment]::GetEnvironmentVariable('Path', $scope) } catch { $v = '' }
        if ($v) { foreach ($p in $v.Split(';')) { if ($p) { [void]$parts.Add($p) } } }
    }
    foreach ($p in @(($env:USERPROFILE + '\.local\bin'), ($env:USERPROFILE + '\.cargo\bin'))) {
        [void]$parts.Add($p)
    }
    $seen = @{}
    $out = New-Object System.Collections.ArrayList
    foreach ($p in $parts) {
        $k = $p.TrimEnd('\').ToLowerInvariant()
        if (-not $seen.ContainsKey($k)) { $seen[$k] = $true; [void]$out.Add($p) }
    }
    $env:Path = ($out -join ';')
}

# -- window control - the whole point of the rewrite --------------------------------------------
# Test-HostWillClose - true when this powershell was started only to run a command and will exit
# (and take its window) the moment we return: -Command / -EncodedCommand / -File, without -NoExit.
# An interactive shell stays open on its own, so it needs no hold on success.
function Test-HostWillClose {
    $argv = @()
    try { $argv = [Environment]::GetCommandLineArgs() } catch { return $false }
    foreach ($a in $argv) { if ($a -match '^-{1,2}noe') { return $false } }
    foreach ($a in $argv) {
        if ($a -match '^-{1,2}(c|com|comm|comma|comman|command|e|ec|enc|encodedcommand|f|fi|fil|file)$') { return $true }
    }
    return $false
}

# Hold-Window - block until a keypress so the message above stays readable. Skipped where nobody
# can press a key (CI, redirected stdin, service account) or when the caller opted out.
function Hold-Window ($prompt) {
    if ($env:ASGARD_NO_PAUSE) { return }
    if ($env:CI) { return }
    try { if ([Console]::IsInputRedirected) { return } } catch { }
    try { if (-not [Environment]::UserInteractive) { return } } catch { }
    Write-Host ""
    Tint ("  " + $prompt) 'DarkGray'
    $read = $false
    try {
        if ($Host.UI -and $Host.UI.RawUI) {
            $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
            $read = $true
        }
    } catch { }
    if (-not $read) { try { $null = Read-Host } catch { } }
    Write-Host ""
}

function Save-Transcript {
    try {
        $dir = $env:TEMP
        if (-not $dir) { $dir = $env:TMP }
        if (-not $dir) { $dir = (Get-Location).Path }
        $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
        $path = Join-Path $dir ("asgard-install-" + $stamp + ".log")
        Set-Content -Path $path -Value ($script:AsgardLog -join [Environment]::NewLine) -Encoding UTF8
        return $path
    } catch { return '' }
}

# Get-EnvReport - the facts a bug report needs. Collected only when something failed, so a healthy
# install stays quiet. Every probe is guarded: the report itself must never be the thing that throws.
function Get-EnvReport {
    $rows = New-Object System.Collections.ArrayList
    try { [void]$rows.Add("powershell    " + $PSVersionTable.PSVersion + " (" + $PSVersionTable.PSEdition + ")") } catch { }
    try { [void]$rows.Add("os            " + [Environment]::OSVersion.VersionString) } catch { }
    try {
        $bits = 'x86'
        if ([Environment]::Is64BitProcess) { $bits = 'x64' }
        $archName = $env:PROCESSOR_ARCHITECTURE
        if (-not $archName) { $archName = 'unknown' }
        [void]$rows.Add("arch          " + $archName + " (process " + $bits + ")")
    } catch { }
    try { [void]$rows.Add("policy        " + (Get-ExecutionPolicy -Scope Process) + " (process)") } catch { }
    foreach ($probe in @(@('uv', '--version'), @('python', '--version'), @('node', '-v'), @('git', '--version'))) {
        $name = $probe[0]
        $line = $name.PadRight(14) + "not found"
        if (Test-Cmd $name) {
            $r = Invoke-Native $name @($probe[1]) -Quiet
            $v = $r.Output
            if ($v) { $v = ($v -split "`n")[0].Trim() }
            if ($r.Code -ne 0) { $v = "present but exit " + $r.Code + " - " + $v }
            $line = $name.PadRight(14) + $v
        }
        [void]$rows.Add($line)
    }
    try { if ($env:HTTPS_PROXY) { [void]$rows.Add("HTTPS_PROXY   " + $env:HTTPS_PROXY) } } catch { }
    return $rows
}

# Show-Failure - the handler that replaces the old `exit 1`. Prints the reason, then everything a
# person needs to act on it: remediation hints, an environment table, and a transcript on disk.
function Show-Failure ($err) {
    $msg = ''
    $where = ''
    try {
        $msg = [string]$err.Exception.Message
        if ($err.InvocationInfo) { $where = $err.InvocationInfo.PositionMessage }
    } catch { $msg = [string]$err }
    $expected = $msg.StartsWith($AsgardFailMark)
    if ($expected) { $msg = $msg.Substring($AsgardFailMark.Length) }

    Write-Host ""
    Tint ("  X  " + $msg) 'Red'
    Add-Log ("  X  " + $msg)
    if (-not $expected) {
        # Unexpected crash - the position block is the only thing that says which line died.
        Add-Log $where
        if ($where) { Tint $where 'DarkGray' }
        Add-Hint 'This one is a bug in the installer, not in your machine. Please report the log below.'
    }
    if ($script:AsgardHints.Count -gt 0) {
        Write-Host ""
        Tint "  try:" 'White'
        foreach ($h in $script:AsgardHints) { Add-Log ("   -> " + $h); Tint ("   -> " + $h) 'DarkGray' }
    }
    Write-Host ""
    Tint "  environment:" 'White'
    foreach ($row in (Get-EnvReport)) { Add-Log ("     " + $row); Tint ("     " + $row) 'DarkGray' }
    $log = Save-Transcript
    if ($log) {
        Write-Host ""
        Tint ("  full log: " + $log) 'DarkGray'
    }
}

# -- install steps -----------------------------------------------------------------------------
function Initialize-Web {
    # TLS 1.2 is not the default in Windows PowerShell 5.1 and github.com refuses anything older.
    # The proxy line matters on managed networks, where an authenticating proxy otherwise answers
    # every download with 407 and no explanation.
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch {
        Write-Warn2 "could not enable TLS 1.2 - downloads may fail on this host"
    }
    try {
        if ([Net.WebRequest]::DefaultWebProxy) {
            [Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultCredentials
        }
    } catch { }
}

# Install-Uv - bootstrap uv the way the host allows, mirroring install.sh's layered fallback.
# The astral.sh script runs in a child shell on purpose: on failure it prints the reason and then
# calls `exit 1`, and in this session that `exit` would take the user's terminal down with it before
# the reason could be read. -EncodedCommand avoids every layer of Windows argument quoting.
function Install-Uv {
    $ps = Get-PowerShellExe
    if ($ps) {
        $inner = '$ErrorActionPreference = "Stop";' +
        '$InformationPreference = "Continue";' +
        '$ProgressPreference = "SilentlyContinue";' +
        '[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12;' +
        'try { [Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultCredentials } catch { };' +
        'Invoke-RestMethod https://astral.sh/uv/install.ps1 -UseBasicParsing | Invoke-Expression'
        $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
        Write-Info "uv via astral.sh (child shell)..."
        $null = Invoke-Native $ps @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-NonInteractive', '-EncodedCommand', $enc)
        Update-PathFromEnvironment
        if (Test-Cmd 'uv') { return $true }
    } else {
        Add-Hint 'no powershell.exe or pwsh.exe was found to host the uv installer'
    }
    if (Test-Cmd 'winget') {
        Write-Info "uv via winget..."
        $null = Invoke-Native 'winget' @('install', '--id', 'astral-sh.uv', '-e', '--source', 'winget',
            '--accept-package-agreements', '--accept-source-agreements')
        Update-PathFromEnvironment
        if (Test-Cmd 'uv') { return $true }
    }
    foreach ($py in @('py', 'python', 'python3')) {
        if (-not (Test-Cmd $py)) { continue }
        Write-Info ("uv via " + $py + " -m pip...")
        $pyArgs = @('-m', 'pip', 'install', '--user', '--upgrade', 'uv')
        if ($py -eq 'py') { $pyArgs = @('-3') + $pyArgs }
        $null = Invoke-Native $py $pyArgs
        Update-PathFromEnvironment
        if (Test-Cmd 'uv') { return $true }
    }
    return $false
}

# Get-LatestVersion - newest published tag (vX.Y.Z -> X.Y.Z). The API is tried first; the
# /releases/latest redirect is the fallback for networks that block api.github.com.
function Get-LatestVersion {
    try {
        $rel = Invoke-RestMethod -Uri ("https://api.github.com/repos/" + $AsgardRepoSlug + "/releases/latest") -UseBasicParsing -TimeoutSec 20
        if ($rel.tag_name -match '^v?([0-9][0-9.]*)$') { return $Matches[1] }
    } catch { Add-Log ("      | releases API: " + $_.Exception.Message) }
    try {
        $resp = Invoke-WebRequest -Uri ("https://github.com/" + $AsgardRepoSlug + "/releases/latest") -UseBasicParsing -TimeoutSec 20 -MaximumRedirection 5
        $url = ''
        if ($resp.BaseResponse -and $resp.BaseResponse.ResponseUri) { $url = [string]$resp.BaseResponse.ResponseUri.AbsoluteUri }
        elseif ($resp.BaseResponse -and $resp.BaseResponse.RequestMessage) { $url = [string]$resp.BaseResponse.RequestMessage.RequestUri.AbsoluteUri }
        if ($url -match '/tag/v?([0-9][0-9.]*)') { return $Matches[1] }
    } catch { Add-Log ("      | releases redirect: " + $_.Exception.Message) }
    return $null
}

# Invoke-Preflight - [1/3]. Reports the environment and returns $true when uv is already usable.
# A function rather than a block inside Main so the smoke can run it on a stripped-down host and read
# what it says, without the install phase behind it reaching the network.
function Invoke-Preflight {
    Phase "preflight - check environment"
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        Add-Hint 'Windows PowerShell 5.1 ships with Windows 10/11 and Server 2016+; older hosts can install PowerShell 7 from https://aka.ms/powershell'
        Fail ("this installer needs PowerShell 5.1 or newer - this is " + $PSVersionTable.PSVersion)
    }
    Write-Ok ("powershell " + $PSVersionTable.PSVersion)
    Initialize-Web

    $haveUv = Test-Cmd 'uv'
    if ($haveUv) {
        $r = Invoke-Native 'uv' @('--version') -Quiet
        Write-Ok ($r.Output + " (already installed)")
    } else {
        Write-Info "uv absent - will bootstrap in step 2"
    }

    # System Python is NOT a prerequisite: uv fetches a standalone CPython 3.14 of its own. It is
    # reported anyway, because "no Python here" is the first thing people suspect when an install
    # dies, and saying so up front is cheaper than the guess. The exit code is what decides, not
    # the mere presence of python.exe: on Windows 10/11 an unused `python` resolves to the Store's
    # app-execution alias, which answers every call with "Python was not found" and exit 9009.
    $pyLine = ''
    if (Test-Cmd 'python') {
        $r = Invoke-Native 'python' @('--version') -Quiet
        if ($r.Code -eq 0) { $pyLine = $r.Output.Trim() }
    }
    if ($pyLine) { Write-Ok ($pyLine + " (not required - uv brings its own)") }
    else { Write-Info "no system python - not required, uv installs a standalone CPython 3.14" }

    # Freyja design engines run on node - checked here in preflight alongside uv/python. The engines
    # and their detector bundle ride in the wheel, so nothing to install for them - but without node
    # the detector, hooks and live mode are all dead, and silence there reads as "clean". We never
    # force-install node (user's runtime choice), and its absence never fails the install.
    $nodeV = ''
    if (Test-Cmd 'node') {
        $r = Invoke-Native 'node' @('-v') -Quiet
        if ($r.Code -eq 0) { $nodeV = $r.Output.Trim() }
    }
    if ($nodeV -match '^v(\d+)') {
        if ([int]$Matches[1] -ge 22) { Write-Ok ("node " + $nodeV + " (design engines)") }
        else { Write-Warn2 ("node " + $nodeV + " - Freyja design engines need >= 22. Upgrade: winget install OpenJS.NodeJS.LTS (or https://nodejs.org)") }
    } else {
        Write-Warn2 "node not found - Freyja design engines (detector/hooks/live) need node >= 22. Install: winget install OpenJS.NodeJS.LTS (or https://nodejs.org). Asgard installs fine without it."
    }
    return $haveUv
}

function Main {
    Write-Host ""
    Tint "  ASGARD" 'White'
    Tint "  make anything, your way" 'DarkGray'

    $haveUv = Invoke-Preflight

    # -- [2/3] install --
    Phase "install - toolchain + asgard"
    if (-not $haveUv) {
        if (-not (Install-Uv)) {
            Add-Hint 'install uv by hand, then re-run this script: https://docs.astral.sh/uv/getting-started/installation/'
            Add-Hint 'on a managed network, set HTTPS_PROXY before re-running'
            Add-Hint 'if uv did install, open a NEW terminal so PATH picks it up'
            Fail "uv bootstrap failed - every method above was tried"
        }
        $r = Invoke-Native 'uv' @('--version') -Quiet
        Write-Ok $r.Output
    }

    # Best-effort: uv downloads the interpreter on demand at install time anyway. Reported honestly
    # either way - the old script printed "OK python 3.14" even when this step had failed.
    Write-Info "preparing python 3.14..."
    $r = Invoke-Native 'uv' @('python', 'install', '3.14')
    if ($r.Code -eq 0) {
        Write-Ok "python 3.14"
    } else {
        Write-Warn2 "python 3.14 pre-install skipped (uv will fetch it on demand)"
        Add-Log $r.Output
    }

    if ($env:ASGARD_INSTALL_SPEC) {
        $from = $env:ASGARD_INSTALL_SPEC
        $desc = 'custom spec'
    } else {
        $v = $env:ASGARD_VERSION
        if (-not $v) { $v = Get-LatestVersion }
        if (-not $v) {
            Add-Hint 'pin the version and retry: $env:ASGARD_VERSION = "X.Y.Z"'
            Add-Hint ("releases: https://github.com/" + $AsgardRepoSlug + "/releases")
            Fail "could not resolve a version to install - github.com was unreachable"
        }
        $from = "https://github.com/" + $AsgardRepoSlug + "/releases/download/v" + $v + "/asgard-" + $v + "-py3-none-any.whl"
        $desc = "v" + $v + " wheel"
    }
    Write-Info ("installing asgard (" + $desc + ")...")
    $r = Invoke-Native 'uv' @('tool', 'install', '--force', '--python', '3.14', $from)
    if ($r.Code -ne 0) {
        Add-Hint 'the uv output above carries the real reason (network, proxy, or a bad version pin)'
        Add-Hint 'pin a known-good version and retry: $env:ASGARD_VERSION = "X.Y.Z"'
        Fail ("install failed (uv exit " + $r.Code + "): " + $from)
    }
    $null = Invoke-Native 'uv' @('tool', 'update-shell') -Quiet
    Update-PathFromEnvironment
    Write-Ok "asgard linked (uv tool)"

    # -- [3/3] verify --
    Phase "verify - check install"
    # PATH was just re-read from the registry, but fall back to uv's bin directory by path before
    # calling this a failure - "installed fine, shell not reloaded" must not read as a broken install.
    $exe = 'asgard'
    if (-not (Test-Cmd $exe)) {
        if ($env:USERPROFILE) {
            $candidate = $env:USERPROFILE + '\.local\bin\asgard.exe'
            if (Test-Path $candidate) { $exe = $candidate }
        }
    }
    $r = Invoke-Native $exe @('--version') -Quiet
    if ($r.Code -ne 0) {
        Add-Log $r.Output
        Add-Hint 'open a NEW terminal and run: asgard --version'
        Add-Hint 'if it is still missing, run: uv tool update-shell'
        Fail "asgard was installed but does not run yet - see the log below"
    }
    Write-Ok ("asgard v" + $r.Output.Trim())
    $cmd = Get-Command asgard -ErrorAction SilentlyContinue
    if ($cmd) { Write-Ok ("on PATH " + $cmd.Source) }
    else { Write-Warn2 "not on PATH yet - restart the terminal (or run: uv tool update-shell)" }

    Write-Host ""
    Tint "  installed" 'Green' -NoNewline; Write-Host " - next:"
    Write-Host "    asgard doctor   " -NoNewline; Tint "# verify" 'DarkGray'
    Write-Host "    asgard --help"
    Write-Host ""
}

# -- entry - the only place allowed to end the process -----------------------------------------
# Everything above throws; nothing above exits. The terminal is held open before any exit so the
# reason stays on screen, and the process code is only forced when the window was closing anyway
# (an interactive shell would be killed by `exit`, which is the failure this rewrite is about).
$script:AsgardFailed = $false
try {
    Main
} catch {
    $script:AsgardFailed = $true
    Show-Failure $_
}
$ErrorActionPreference = $script:AsgardPrevEap
$ProgressPreference = $script:AsgardPrevProgress
if ($script:AsgardFailed) {
    Hold-Window "install failed - press any key to close this window."
    $global:LASTEXITCODE = 1
    # Only when the window was closing regardless. There is no second condition worth adding here:
    # an earlier `-or $env:CI` looked harmless and was not - on a CI runner it ended a host shell
    # that had piped this script in, which is the whole bug. Automation still gets a real exit code,
    # because -Command / -File is how automation invokes a script, and that is what this detects.
    if (Test-HostWillClose) { exit 1 }
} elseif (Test-HostWillClose) {
    Hold-Window "press any key to close this window."
}
