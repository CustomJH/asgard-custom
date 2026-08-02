# install.ps1 behavioural smoke - drives the failure paths without installing anything.
#
# The static test (tests/test_install_ps1.py) proves the shape; this proves the behaviour. It loads
# everything ABOVE the entry marker (so Main never runs), swaps in a fake Main, and executes the real
# entry block in a child shell. What is being checked is the one thing users reported: a failure has
# to leave a readable message behind instead of taking the terminal with it.
#
# Run: pwsh -NoProfile -File tests/install_ps1_smoke.ps1
$ErrorActionPreference = 'Stop'

# Save-Transcript used to fall back to the CURRENT DIRECTORY when both TEMP and TMP were unset -
# which is every non-Windows host - and this smoke drives the failure path half a dozen times per
# run, so it buried the repository root in asgard-install-*.log (306 of them had accumulated before
# this line existed; 33 stale ones were still lying around on 26-08-02). install.ps1 now reaches
# TMPDIR and [IO.Path]::GetTempPath() before the working directory, so the litter is fixed at the
# source. This line stays as the belt to that braces: it pins the destination for this run
# regardless of what the installer's fallback chain decides, and the sweep at the bottom of this
# file is what actually removes the files.
if (-not $env:TEMP -and -not $env:TMP) { $env:TEMP = [IO.Path]::GetTempPath() }

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
$script:Transcripts = New-Object System.Collections.ArrayList
# Add-Transcript <text> - remember every "full log: …" path a scenario announced. Noted rather
# than deleted on the spot, because one check has to open the file and read it back; the sweep runs
# at the end. Anything that drives the failure path must go through here or the logs pile up.
function Add-Transcript ($text) {
    foreach ($m in ([regex]::Matches([string]$text, 'full log: (\S+)'))) {
        [void]$script:Transcripts.Add($m.Groups[1].Value.Trim())
    }
}
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

# -- terminal capability: three tiers, and the console handed back --------------------------------
# The reported symptom is "no progress bar, nothing moves". The cure is a banner and a spinner, and
# both exist only if the capability probe answers correctly - a wrong answer either prints boxes or
# prints nothing at all. Each tier is driven here directly, in process, where the answer is readable.
$prevUi = $env:ASGARD_FORCE_UI
$prevAscii = $env:ASGARD_ASCII
$prevVersion = $env:ASGARD_VERSION
$prevNoColor = $env:NO_COLOR
$encBefore = [Console]::OutputEncoding

# ASGARD_FORCE_UI is set alongside NO_COLOR on purpose. Without it this smoke's own stdout is
# redirected, the probe bails on that instead, and the check passes while NO_COLOR does nothing -
# measured: deleting the NO_COLOR line from install.ps1 left this green. NO_COLOR must WIN over a
# request for the full UI, and setting both is the only way to ask that question.
$env:ASGARD_FORCE_UI = '1'; $env:ASGARD_ASCII = ''; $env:NO_COLOR = '1'
Invoke-Expression $body
Initialize-Terminal
Check 'NO_COLOR leaves the installer plain' ((-not $script:AsgardColor) -and (-not $script:AsgardAnim)) 'colour or animation survived NO_COLOR'
Check 'NO_COLOR keeps the ASCII glyph set' ((Get-Glyph 'ok') -eq '+') ("got '" + (Get-Glyph 'ok') + "'")

$env:NO_COLOR = ''; $env:ASGARD_FORCE_UI = '1'; $env:ASGARD_ASCII = '1'
Invoke-Expression $body
Initialize-Terminal
Check 'ASGARD_ASCII keeps colour and motion' ($script:AsgardColor -and $script:AsgardAnim) 'the ASCII tier lost colour or animation'
Check 'ASGARD_ASCII drops the Unicode set' ((-not $script:AsgardRich) -and ((Get-Glyph 'ok') -eq '+')) ("got '" + (Get-Glyph 'ok') + "'")
Check 'the ASCII wheel has four frames' ($script:AsgardGlyph['spin'].Count -eq 4) ("got " + $script:AsgardGlyph['spin'].Count)

# Whether this host's console can be put into UTF-8 is the host's answer to give, not this test's to
# assume - a Windows runner, a Windows Terminal and a pipe are three different answers, and hard-coding
# one of them would either pass vacuously or fail on a machine that is behaving correctly. So the
# question is put to the console directly (and put straight back), and the tier is then required to
# MATCH it: never claim a glyph set the console cannot deliver, never refuse one it can.
$utf8Possible = $false
try {
    $probe = [Console]::OutputEncoding
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $utf8Possible = ([Console]::OutputEncoding.CodePage -eq 65001)
    [Console]::OutputEncoding = $probe
} catch { $utf8Possible = $false }

$env:ASGARD_ASCII = ''; $env:ASGARD_VERSION = '9.9.9'
Invoke-Expression $body
Initialize-Terminal
Check 'the Unicode tier tracks what the console can take' ($script:AsgardRich -eq $utf8Possible) ("rich=" + $script:AsgardRich + ", console accepts UTF-8=" + $utf8Possible)
$wantOk = '+'
$wantFrames = 4
if ($utf8Possible) { $wantOk = [string][char]0x2714; $wantFrames = 8 }
Check 'the check mark is the one install.sh prints' ((Get-Glyph 'ok') -eq $wantOk) ("got '" + (Get-Glyph 'ok') + "'")
Check 'the wheel has the frame count of its tier' ($script:AsgardGlyph['spin'].Count -eq $wantFrames) ("got " + $script:AsgardGlyph['spin'].Count)
if ($utf8Possible) {
    Check 'the console was switched to UTF-8 for it' ([Console]::OutputEncoding.CodePage -eq 65001) ("got " + [Console]::OutputEncoding.CodePage)
}

$banner = Write-Banner *>&1 | Out-String
Check 'the banner carries the version' ($banner -match '\(v9\.9\.9\)') $banner
Check 'the banner carries the tagline' ($banner -match 'make anything, your way') $banner
Check 'the banner draws the lockup' ((@($banner -split "`n" | Where-Object { $_.Trim() }).Count) -ge 8) $banner

Restore-Terminal
Check 'the console encoding is handed back' (([Console]::OutputEncoding.CodePage -eq $encBefore.CodePage) -and ($null -eq $script:AsgardPrevOutEnc)) ("got " + [Console]::OutputEncoding.CodePage + ", wanted " + $encBefore.CodePage)

# -- native argument quoting ----------------------------------------------------------------------
# Start-Process joins its -ArgumentList with a plain space and quotes nothing, so an argument holding
# a space arrives at the child split in two. Measured here before this was fixed: `sh -c 'sleep 2; …'`
# reached the child as four arguments and died on its own usage message. An install source of
# `C:\Users\Jane Doe\asgard` is the ordinary way a user meets that.
Check 'a plain argument is passed through untouched' ((Format-NativeArg 'plain') -eq 'plain') (Format-NativeArg 'plain')
Check 'an argument with a space is quoted' ((Format-NativeArg 'has space') -eq '"has space"') (Format-NativeArg 'has space')
Check 'an embedded quote is escaped' ((Format-NativeArg 'a"b') -eq '"a\"b"') (Format-NativeArg 'a"b')
Check 'a trailing backslash is doubled inside the quotes' ((Format-NativeArg 'C:\x y\') -eq '"C:\x y\\"') (Format-NativeArg 'C:\x y\')
Check 'an empty argument survives as an empty argument' ((Format-NativeArg '') -eq '""') (Format-NativeArg '')

$env:ASGARD_FORCE_UI = $prevUi; $env:ASGARD_ASCII = $prevAscii
$env:ASGARD_VERSION = $prevVersion; $env:NO_COLOR = $prevNoColor
Invoke-Expression $body

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
    Add-Transcript $out
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

# -- the spinner, end to end ----------------------------------------------------------------------
# The whole point of the change: a slow step has to look alive. Driven in a child so the animation
# is written to a real stream and can be read back. The ASCII tier is used on purpose - the braille
# frames would have to survive a console-code-page round trip on the way out of the child, and this
# check is about motion, not about fonts.
$spinFake = @'
function Main {
    Initialize-Terminal
    $exe = (Get-Process -Id $PID).Path
    $inner = "Start-Sleep -Milliseconds 500; Write-Output 'spaced ok'; [Console]::Error.WriteLine('err line'); exit 5"
    $r = Invoke-Native $exe @('-NoProfile', '-Command', $inner) -Spin 'slow step in flight...'
    Write-Host ("SPINRC=" + $r.Code)
    Write-Host ("SPINOUT=" + ($r.Output -replace "\s+", ' '))
}
'@
$env:ASGARD_FORCE_UI = '1'
$env:ASGARD_ASCII = '1'
$s = Run-Scenario $spinFake '1'
$env:ASGARD_FORCE_UI = $prevUi
$env:ASGARD_ASCII = $prevAscii

Check 'a spun step reports its exit code' ($s.Out -match 'SPINRC=5') $s.Out
Check 'a spun step keeps the child stdout' ($s.Out -match 'SPINOUT=[^\r\n]*spaced ok') $s.Out
Check 'a spun step keeps the child stderr' ($s.Out -match 'SPINOUT=[^\r\n]*err line') $s.Out
$esc = [char]27
$frames = @($s.Out -split "`n" | Where-Object { $_ -match 'slow step in flight' } |
    ForEach-Object { $_ -replace ($esc + '\[[0-9;]*m'), '' })
Check 'the spinner redraws while the step runs' ($frames.Count -ge 3) ("frames drawn: " + $frames.Count)
$wheel = @($frames | ForEach-Object { if ($_ -match '^\s*(\S)\s') { $Matches[1] } } | Sort-Object -Unique)
Check 'the spinner actually turns' ($wheel.Count -ge 2) ("distinct frames: '" + ($wheel -join '') + "'")
# The frames end in a carriage return, not a newline. If the line is not wiped when the step ends,
# whatever prints next lands ON TOP of the last frame - the result mark would read
# "  / installing asgard...OK asgard". Cleared, SPINRC starts its own line; uncleared, it does not.
Check 'the spinner line is wiped before the next line prints' ($s.Out -match '(?m)^\s*SPINRC=5') $s.Out

# Redirected output (CI, `> log.txt`) cannot animate. The step must still announce itself and still
# report honestly - a silent success there reads exactly like a hang.
$s = Run-Scenario $spinFake '1'
Check 'without animation the step still names itself' ($s.Out -match 'slow step in flight') $s.Out
Check 'without animation the exit code still comes back' ($s.Out -match 'SPINRC=5') $s.Out
Check 'without animation the child output is still captured' ($s.Out -match 'SPINOUT=[^\r\n]*spaced ok') $s.Out

# -- the mechanism itself: does `irm | iex` survive a failure? ------------------------------------
# This is the user-visible claim, tested directly. A host shell is started reading commands from
# stdin - the shape of a person who opened PowerShell and pasted the install line - and told to print
# a marker AFTER the pasted script finishes. If the script ends the session, the marker never runs.
# The control case proves the probe can actually detect the old behaviour.
function Test-HostSurvives ($scriptPath) {
    $lines = @(('Get-Content "' + $scriptPath + '" -Raw | Invoke-Expression'), 'Write-Host "HOST-SURVIVED"')
    $out = $lines | & $psExe -NoProfile -ExecutionPolicy Bypass - 2>&1 | Out-String
    Add-Transcript $out
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

foreach ($t in $script:Transcripts) { Remove-Item $t -Force -ErrorAction SilentlyContinue }

Write-Host ""
if ($script:Bad -gt 0) {
    Write-Host ("  " + $script:Bad + " check(s) failed") -ForegroundColor Red
    exit 1
}
Write-Host "  install.ps1 smoke: all checks passed" -ForegroundColor Green
exit 0
