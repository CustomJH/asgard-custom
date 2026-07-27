# install.ps1 behavioural smoke - drives the failure paths without installing anything.
#
# The static test (tests/test_install_ps1.py) proves the shape; this proves the behaviour. It loads
# everything ABOVE the entry marker (so Main never runs), swaps in a fake Main, and executes the real
# entry block in a child shell. What is being checked is the one thing users reported: a failure has
# to leave a readable message behind instead of taking the terminal with it.
#
# Run: pwsh -NoProfile -File tests/install_ps1_smoke.ps1
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$srcPath = Join-Path $root 'install.ps1'
$src = Get-Content $srcPath -Raw
$mark = '# -- entry'
$idx = $src.IndexOf($mark)
if ($idx -lt 0) { throw "entry marker '$mark' not found in $srcPath" }
$body = $src.Substring(0, $idx)
$tail = $src.Substring($idx)

$script:Bad = 0
function Check ($name, $cond, $detail) {
    if ($cond) {
        Write-Host "  ok   " -ForegroundColor Green -NoNewline; Write-Host $name
    } else {
        $script:Bad++
        Write-Host "  FAIL " -ForegroundColor Red -NoNewline; Write-Host ($name + "  ::  " + $detail)
    }
}

# Load the function definitions only. If this throws, the script has a load-time fault - which is
# exactly the failure that used to leave users with a closed window and nothing else.
Invoke-Expression $body

$psExe = (Get-Process -Id $PID).Path

# -- Invoke-Native: reports by exit code, never by exception --------------------------------------
$r = Invoke-Native 'definitely-not-a-real-command-9134' @() -Quiet
Check 'missing command returns 9009' ($r.Code -eq 9009) ("got " + $r.Code)

$r = Invoke-Native $psExe @('-NoProfile', '-Command', 'exit 7') -Quiet
Check 'exit code is passed through' ($r.Code -eq 7) ("got " + $r.Code)

# The regression this helper exists for: a native command that writes to stderr and SUCCEEDS. In
# Windows PowerShell, redirected native stderr becomes an ErrorRecord, and under
# $ErrorActionPreference='Stop' that aborted the whole install on a step that had worked - uv writes
# its progress to stderr, so the healthy case was the one that killed the run.
$ErrorActionPreference = 'Stop'
$threw = $false
try {
    # Inner quotes are single on purpose: Windows PowerShell 5.1 does not escape embedded double
    # quotes when it builds a native command line, so a `"…"` payload reaches the child mangled and
    # it dies with exit 1 - measured on a Windows runner. install.ps1 sidesteps the whole class by
    # passing its child payload as -EncodedCommand.
    $r = Invoke-Native $psExe @('-NoProfile', '-Command', "[Console]::Error.WriteLine('progress'); exit 0") -Quiet
} catch { $threw = $true }
Check 'stderr on a succeeding command does not throw' (-not $threw) 'Invoke-Native let a NativeCommandError escape'
Check 'stderr on a succeeding command reads as success' ($r.Code -eq 0) ("got " + $r.Code)
Check 'preference is restored after the call' ($ErrorActionPreference -eq 'Stop') ("got " + $ErrorActionPreference)

# -- Fail: throws, never exits --------------------------------------------------------------------
$caught = ''
try { Fail 'boom' } catch { $caught = $_.Exception.Message }
Check 'Fail throws with the marker' ($caught -eq 'ASGARD_FAIL::boom') ("got '" + $caught + "'")

# -- entry block, end to end, in a child shell ----------------------------------------------------
# run-scenario <fakeMain> -> @{ Code; Out }. The child is started with -File, so Test-HostWillClose
# sees a window that is about to close - the same shape as a user double-clicking the installer.
function Run-Scenario ($fakeMain, $env_no_pause) {
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("asgard-smoke-" + [Guid]::NewGuid().ToString('N') + ".ps1")
    Set-Content -Path $tmp -Value ($body + "`n" + $fakeMain + "`n" + $tail) -Encoding UTF8
    $prev = $env:ASGARD_NO_PAUSE
    $env:ASGARD_NO_PAUSE = $env_no_pause
    try {
        $out = & $psExe -NoProfile -ExecutionPolicy Bypass -File $tmp 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally {
        $env:ASGARD_NO_PAUSE = $prev
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
    return (New-Object psobject -Property @{ Code = $code; Out = $out })
}

$s = Run-Scenario 'function Main { Fail "simulated bootstrap failure" }' '1'
Check 'expected failure exits 1' ($s.Code -eq 1) ("got " + $s.Code)
Check 'expected failure prints the reason' ($s.Out -match 'X\s+simulated bootstrap failure') $s.Out
Check 'expected failure prints the environment table' ($s.Out -match 'environment:') $s.Out
Check 'expected failure names a log file' ($s.Out -match 'full log: (.+)') $s.Out
if ($s.Out -match 'full log: (\S+)') {
    # Not $log: PowerShell variable names are case-insensitive, so a local $log IS the script's
    # $Log - naming it that clobbered the loaded transcript with a string and the next in-process
    # call died on [String].Add(). install.ps1 now namespaces its own state for the same reason.
    $logPath = $Matches[1].Trim()
    Check 'the log file exists' (Test-Path $logPath) $logPath
    if (Test-Path $logPath) {
        $logText = Get-Content $logPath -Raw
        Check 'the log carries the reason' ($logText -match 'simulated bootstrap failure') $logText
        Remove-Item $logPath -Force -ErrorAction SilentlyContinue
    }
}
Check 'expected failure stays quiet about installer bugs' (-not ($s.Out -match 'bug in the installer')) $s.Out

$s = Run-Scenario 'function Main { throw "unexpected kaboom" }' '1'
Check 'unexpected crash exits 1' ($s.Code -eq 1) ("got " + $s.Code)
Check 'unexpected crash prints the reason' ($s.Out -match 'unexpected kaboom') $s.Out
Check 'unexpected crash is labelled a bug' ($s.Out -match 'bug in the installer') $s.Out

$s = Run-Scenario 'function Main { Write-Ok "pretend install" }' '1'
Check 'success exits 0' ($s.Code -eq 0) ("got " + $s.Code)
Check 'success prints no failure marker' (-not ($s.Out -match '  X  ')) $s.Out

# Without ASGARD_NO_PAUSE the hold must still not block a non-interactive run: the child's stdin is
# redirected, and Hold-Window checks that before waiting on a key. A regression here hangs CI.
$s = Run-Scenario 'function Main { Fail "held" }' ''
Check 'a redirected stdin never blocks on the hold' ($s.Code -eq 1) ("got " + $s.Code)

# -- the mechanism itself: does `irm | iex` survive a failure? ------------------------------------
# This is the user-visible claim, tested directly. A host shell is started reading commands from
# stdin - the shape of a person who opened PowerShell and pasted the install line - and told to print
# a marker AFTER the pasted script finishes. If the script ends the session, the marker never runs.
# The control case proves the probe can actually detect the old behaviour.
function Test-HostSurvives ($scriptPath) {
    $lines = @(('Get-Content "' + $scriptPath + '" -Raw | Invoke-Expression'), 'Write-Host "HOST-SURVIVED"')
    $out = $lines | & $psExe -NoProfile -ExecutionPolicy Bypass - 2>&1 | Out-String
    return ($out -match 'HOST-SURVIVED')
}

$oldStyle = Join-Path ([IO.Path]::GetTempPath()) ("asgard-smoke-oldstyle-" + [Guid]::NewGuid().ToString('N') + ".ps1")
Set-Content -Path $oldStyle -Value "Write-Host '  X  uv install failed'`nexit 1" -Encoding UTF8
Check 'control: an exiting script does kill the host session' (-not (Test-HostSurvives $oldStyle)) 'the probe cannot detect the bug it exists for'
Remove-Item $oldStyle -Force -ErrorAction SilentlyContinue

$newStyle = Join-Path ([IO.Path]::GetTempPath()) ("asgard-smoke-newstyle-" + [Guid]::NewGuid().ToString('N') + ".ps1")
Set-Content -Path $newStyle -Value ($body + "`nfunction Main { Fail 'uv bootstrap failed' }`n" + $tail) -Encoding UTF8
$env:ASGARD_NO_PAUSE = '1'
Check 'a failing install leaves the host session alive' (Test-HostSurvives $newStyle) 'install.ps1 took the pasted-into shell down with it'
Remove-Item $newStyle -Force -ErrorAction SilentlyContinue

# -- the reported scenario's preflight: no uv, no python, no node ---------------------------------
# PATH is stripped to an empty directory and preflight is run IN PROCESS. Running the whole script
# here instead would be neither hermetic nor safe: on a Windows PowerShell 7 host the bootstrap still
# finds its own shell through $PSHOME, so the "no tools" case went on to download uv and install
# asgard for real - a test must not mutate the machine it runs on, and must not depend on a network.
$emptyDir = Join-Path ([IO.Path]::GetTempPath()) ("asgard-smoke-nopath-" + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $emptyDir -Force
$prevPath = $env:PATH
$env:PATH = $emptyDir
$bare = ''
$bareThrew = $false
try { $bare = Invoke-Preflight *>&1 | Out-String } catch { $bareThrew = $true; Write-Host ('    ' + $_.Exception.Message) }
finally {
    $env:PATH = $prevPath
    Remove-Item $emptyDir -Recurse -Force -ErrorAction SilentlyContinue
}
Check 'bare host: preflight does not fail on an empty machine' (-not $bareThrew) 'preflight threw with no tools installed'
Check 'bare host: says a missing system python is fine' ($bare -match 'no system python[^\r\n]*not required') $bare
Check 'bare host: says a missing node still installs' ($bare -match 'Asgard installs fine without it') $bare
Check 'bare host: notes uv will be bootstrapped' ($bare -match 'uv absent') $bare

# -- native-command errors stay errors, not aborts ------------------------------------------------
# PowerShell 7.3+ can promote a non-zero native exit to a terminating error, which is the modern
# equivalent of the Windows PowerShell 5.1 NativeCommandError trap. Invoke-Native must be deaf to it.
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $true
    $ErrorActionPreference = 'Stop'
    $threw = $false
    try { $r = Invoke-Native $psExe @('-NoProfile', '-Command', 'exit 3') -Quiet } catch { $threw = $true }
    Check 'a non-zero native exit does not abort the script' (-not $threw) 'Invoke-Native let a native error escape'
    Check 'a non-zero native exit is still reported' ($r.Code -eq 3) ("got " + $r.Code)
    $PSNativeCommandUseErrorActionPreference = $false
}

# -- the piped case leaves the user's session as it found it --------------------------------------
# `irm | iex` runs the script IN the user's shell, so its preference assignments are theirs. Run the
# whole thing in-process (success path, so the tail does not exit) and check they came back. This
# clobbers the loaded state, so it goes last.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'Continue'
$env:ASGARD_NO_PAUSE = '1'
Invoke-Expression ($body + "`nfunction Main { }`n" + $tail)
Check 'ErrorActionPreference is restored to the session value' ($ErrorActionPreference -eq 'Continue') ("got " + $ErrorActionPreference)
Check 'ProgressPreference is restored to the session value' ($ProgressPreference -eq 'Continue') ("got " + $ProgressPreference)

Write-Host ""
if ($script:Bad -gt 0) {
    Write-Host ("  " + $script:Bad + " check(s) failed") -ForegroundColor Red
    exit 1
}
Write-Host "  install.ps1 smoke: all checks passed" -ForegroundColor Green
exit 0
