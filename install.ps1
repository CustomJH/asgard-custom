# Asgard installer - Windows PowerShell entry point. Same flow as install.sh:
# uv bootstrap -> standalone CPython 3.14 -> `uv tool install asgard`. No system Python/Node/git.
#   irm https://raw.githubusercontent.com/CustomJH/asgard-custom/main/install.ps1 | iex
# Env: ASGARD_VERSION (pin X.Y.Z) - ASGARD_INSTALL_SPEC (override source) - ASGARD_NO_PAUSE=1 -
#      NO_COLOR (plain output) - ASGARD_FORCE_UI=1 (draw the full UI even when stdout is redirected) -
#      ASGARD_ASCII=1 (keep the colour and the spinner, drop the Unicode glyph set)
#
# This file is deliberately ASCII-only and Windows PowerShell 5.1 syntax-only. It is fetched as text
# and run through Invoke-Expression, so one PS7-only operator or one mis-decoded byte would take the
# whole script down at parse time - before any handler inside it could say why. Every glyph the user
# sees is therefore built at RUNTIME from a code point ([char]0x2714) or from a base64 payload, never
# typed into the source: the look matches install.sh without a single non-ASCII byte on the wire.
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
$ProgressPreference = 'SilentlyContinue'   # we draw our own activity; IWR's bar is slow and noisy

$AsgardRepoSlug = 'CustomJH/asgard-custom'
$AsgardFailMark = 'ASGARD_FAIL::'

$script:AsgardLog = New-Object System.Collections.ArrayList
$script:AsgardHints = New-Object System.Collections.ArrayList
$script:AsgardStep = 0

# -- terminal capability ------------------------------------------------------------------------
# Three separate questions, because on Windows they have three different answers:
#   colour    - can we tint at all (a console, and the user did not set NO_COLOR)
#   VT        - are ANSI escapes understood (bold and dim exist ONLY here; the console-attribute
#               API that every Windows host has had since forever knows neither)
#   rich      - can the console DRAW the Unicode set. This is a property of the terminal's font,
#               not of the shell, and only a terminal that names itself can be trusted with it.
#               Legacy conhost names itself nowhere and answers a braille glyph with a box.
# Defaults are the ASCII set, so a failure anywhere above still leaves every surface printable.
$script:AsgardColor = $false
$script:AsgardVT = $false
$script:AsgardRich = $false
$script:AsgardAnim = $false
$script:AsgardPrevOutEnc = $null
$script:AsgardGlyph = @{
    ok = '+'; warn = '!'; info = '-'; fail = 'X'; sep = '-'
    spin = @('-', '\', '|', '/')
}

# install.sh's palette, expressed twice: as SGR parameters for hosts that speak ANSI, and as
# ConsoleColor names for hosts that do not. Same names on both sides so a call site never chooses.
$script:AsgardSgr = @{ ok = '32'; warn = '33'; fail = '31'; info = '2'; step = '1;36'; head = '1;97'; strong = '1'; dim = '2' }
$script:AsgardCC = @{ ok = 'Green'; warn = 'Yellow'; fail = 'Red'; info = 'DarkGray'; step = 'Cyan'; head = 'White'; strong = 'White'; dim = 'DarkGray' }

# install.sh's braille wheel, by code point: U+28FE U+28FD U+28FB U+28BF U+287F U+28DF U+28EF U+28F7
$script:AsgardSpinCp = @(0x28FE, 0x28FD, 0x28FB, 0x28BF, 0x287F, 0x28DF, 0x28EF, 0x28F7)

# The brand lockup - byte-identical to install.sh's ART block, carried as base64 because the source
# file must stay ASCII. tests/test_install_ps1.py decodes this and compares it to install.sh, so the
# two installers cannot drift apart silently.
$script:AsgardLogo = @(
    'ICDioIDioIDioIDioIDiooDioaTio7bio7bio7bio7LioKTio4DioIDioIDioIDioIAgIOKggOKggOKggOKisOKhhOKggOKggOKggOKggOKg',
    'gOKigOKjpOKjpuKjhOKhgOKggOKggOKggOKggOKjoOKjpuKjgOKggOKggOKggOKggOKggOKggOKjpuKggOKggOKggOKggOKgsOKjtuKjtuKj',
    'tuKjpuKhgOKggOKggOKgkOKjtuKjpuKjhOKggOKggOKggAogIOKggOKggOKigOKjvOKjveKju+Khn+Kjv+Kjt+Kiq+Kjn+Kjr+Kjp+KhgOKg',
    'gOKggCAg4qCA4qCA4qKA4qO/4qO34qCA4qCA4qCA4qCA4qKw4qO/4qCL4qCI4qCZ4qCB4qCA4qCA4qOg4qG+4qCL4qCI4qCb4qCA4qCA4qCA',
    '4qCA4qCA4qO44qO/4qGG4qCA4qCA4qCA4qCA4qO/4qGH4qCA4qCZ4qO34qGE4qCA4qCA4qO/4qGP4qC74qO34qGE4qCACiAg4qCA4qCA4qO4',
    '4qK94qOm4qG34qO74qO74qGf4qOf4qK+4qO04qOv4qOn4qCA4qCAICDioIDioIDio7zioY/iorvio4fioIDioIDioIDioIjioJviorfio6Ti',
    'oYDioIDioIDiorjio7/ioIHioIDioIDio4Dio4DioIDioIDioIDioqDio7/ioJnio7/ioYDioIDioIDioIDio7/ioYfio4Dio7TioJ/ioIDi',
    'oIDioIDio7/ioYfioIDioIjiorvioYYKICDioIDioIDiorvioL3ioIfioIHio7jiorjioYfio7fioIjioLjioK/ioZ/ioIDioIAgIOKggOKi',
    'sOKhv+KigOKhiOKjv+KhhOKggOKggOKggOKggOKggOKgmeKiv+KjpuKggOKgmOKiv+KjhOKggOKggOKiueKhj+KggOKggOKggOKjvuKgh+Kj',
    'gOKiueKjp+KggOKggOKggOKjv+Khv+Kiu+Kjp+KggOKggOKggOKggOKjv+Khh+KggOKjoOKhv+KggwogIOKggOKggOKgiOKis+KjsuKjtuKh',
    'v+KjvuKjt+Kiv+KjtuKjluKhnuKggeKggOKggCAg4qKA4qO/4qCB4qC74qCD4qK44qO34qGA4qCA4qCw4qO24qOk4qO04qC/4qCD4qCA4qCA',
    '4qCA4qCZ4qK34qOk4qO84qGH4qCA4qCA4qO44qGf4qCY4qCf4qCB4qK74qOG4qCA4qCA4qO/4qGH4qCA4qC54qO34qGA4qCA4qCA4qO/4qOn',
    '4qG+4qCL4qCA4qCACiAg4qCA4qCA4qCA4qCA4qCI4qCT4qC74qCv4qC14qCf4qCa4qCJ4qCA4qCA4qCA4qCAICDioInioInioIHioIDioIDi',
    'oIjioInioIHioIDioIDioIDioInioIHioIDioIDioIDioIDioIDioIDioIDioInioLnioIPioIDioIjioInioInioIDioIDioIDioInioIni',
    'oIHioIjioInioInioIDioIDioIjioInioIDioIjioInioInioIDioIDioIDioIAKICDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi',
    'lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAg4peHIOKUgOKUgOKUgOKUgOKU',
    'gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU',
    'gA=='
)
$script:AsgardLogoWidth = 68

# The same lockup for a console that cannot draw braille - a wordmark in characters every Windows
# font has had since code page 437. Not a downgrade to a bare word: the install should look like the
# same product on conhost as it does in Windows Terminal.
$script:AsgardWordmark = @(
    '      _    ____   ____    _    ____  ____',
    '     / \  / ___| / ___|  / \  |  _ \|  _ \',
    '    / _ \ \___ \| |  _  / _ \ | |_) | | | |',
    '   / ___ \ ___) | |_| |/ ___ \|  _ <| |_| |',
    '  /_/   \_\____/ \____/_/   \_\_| \_\____/',
    '  ------------------ <> -------------------'
)
$script:AsgardWordmarkWidth = 43

function Initialize-Terminal {
    if ($env:NO_COLOR) { return }
    $forced = $false
    if ($env:ASGARD_FORCE_UI) { $forced = $true }
    $redirected = $false
    try { $redirected = [Console]::IsOutputRedirected } catch { $redirected = $false }
    if ($redirected -and -not $forced) { return }
    $script:AsgardColor = $true
    $script:AsgardAnim = $true
    try { if ($Host.UI -and $Host.UI.SupportsVirtualTerminal) { $script:AsgardVT = $true } } catch { }
    if ($forced) { $script:AsgardVT = $true }

    # A terminal that identifies itself is a terminal with a modern font stack and glyph fallback.
    # Windows Terminal, ConEmu, VS Code and every third-party emulator set one of these; the legacy
    # console sets none of them, and that silence is the signal to stay on the ASCII set.
    # ASGARD_ASCII is the manual override for a console that names itself and still cannot draw
    # (a pinned raster font) - the mirror of install.sh's ASGARD_NO_IMAGE.
    if ($env:ASGARD_ASCII) { return }
    $named = $false
    foreach ($v in @($env:WT_SESSION, $env:ConEmuANSI, $env:TERM_PROGRAM, $env:TERM, $env:ASGARD_FORCE_UI)) {
        if ($v) { $named = $true }
    }
    if (-not $named) { return }
    # Nothing above ASCII reaches the screen until the console is told to speak UTF-8: the default
    # output encoding is the OEM code page, which turns every glyph we own into a question mark.
    try {
        $script:AsgardPrevOutEnc = [Console]::OutputEncoding
        [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    } catch {
        $script:AsgardPrevOutEnc = $null
        return
    }
    $frames = @()
    foreach ($cp in $script:AsgardSpinCp) { $frames += [string][char]$cp }
    $script:AsgardGlyph = @{
        ok = [string][char]0x2714      # heavy check
        warn = '!'
        info = [string][char]0x00B7    # middle dot
        fail = [string][char]0x2717    # ballot X
        sep = [string][char]0x00B7
        spin = $frames
    }
    $script:AsgardRich = $true
}

# Restore-Terminal - the console code page is process-wide state, and under `irm | iex` the process
# is the user's own shell. Whatever we changed goes back exactly as the preferences do.
function Restore-Terminal {
    if ($script:AsgardPrevOutEnc) {
        try { [Console]::OutputEncoding = $script:AsgardPrevOutEnc } catch { }
        $script:AsgardPrevOutEnc = $null
    }
}

function Get-Glyph ($name) { return [string]$script:AsgardGlyph[$name] }

function Get-ConsoleWidth {
    $w = 0
    try { if ($Host.UI -and $Host.UI.RawUI -and $Host.UI.RawUI.WindowSize) { $w = [int]$Host.UI.RawUI.WindowSize.Width } } catch { $w = 0 }
    if ($w -lt 40) { $w = 80 }
    return $w
}

# -- output - every line also lands in the transcript we can write out on failure ---------------
function Add-Log ($text) { [void]$script:AsgardLog.Add([string]$text) }
function Add-Hint ($text) { [void]$script:AsgardHints.Add([string]$text) }

# Write-Part <text> <role> - one fragment in one role. ANSI where it is understood, because bold and
# dim carry half of install.sh's look and the console-attribute API has neither; console colours
# otherwise, so a host without VT still gets green/yellow/red rather than a wall of grey.
function Write-Part ($text, $role, [switch]$NoNewline) {
    if (-not $script:AsgardColor -or -not $role) { Write-Host $text -NoNewline:$NoNewline; return }
    if ($script:AsgardVT -and $script:AsgardSgr.ContainsKey($role)) {
        $esc = [string][char]27
        Write-Host ($esc + '[' + $script:AsgardSgr[$role] + 'm' + $text + $esc + '[0m') -NoNewline:$NoNewline
        return
    }
    if ($script:AsgardCC.ContainsKey($role)) {
        Write-Host $text -ForegroundColor $script:AsgardCC[$role] -NoNewline:$NoNewline
        return
    }
    Write-Host $text -NoNewline:$NoNewline
}

# Write-Mark <role> <msg> <detail> - install.sh's result line: two spaces, a tinted glyph, the
# message, and the parenthetical detail dimmed behind it. The transcript keeps an ASCII tag instead
# of the glyph, so a log file stays readable wherever it is opened.
function Write-Mark ($role, $msg, $detail) {
    $tag = @{ ok = 'OK'; warn = '!'; info = '.'; fail = 'X' }[$role]
    $line = '  ' + ([string]$tag).PadRight(3) + $msg
    if ($detail) { $line = $line + ' ' + $detail }
    Add-Log $line
    Write-Host '  ' -NoNewline
    Write-Part (Get-Glyph $role) $role -NoNewline
    Write-Host (' ' + $msg) -NoNewline
    if ($detail) { Write-Part (' ' + $detail) 'dim' -NoNewline }
    Write-Host ''
}

function Write-Ok ($msg, $detail) { Write-Mark 'ok' $msg $detail }
function Write-Info ($msg, $detail) { Write-Mark 'info' $msg $detail }
function Write-Warn2 ($msg, $detail) { Write-Mark 'warn' $msg $detail }
function Write-Trace ($msg) { Add-Log ("      | " + $msg); Write-Part ("      | " + $msg) 'dim' }

# Fail <msg> - expected, explained failure. Throws instead of exiting so the terminal survives long
# enough to show the reason; the marker tells the bottom handler this is a message, not a crash.
function Fail ($msg) { throw ($AsgardFailMark + $msg) }

function Phase ($title) {
    $script:AsgardStep++
    Write-Host ""
    Add-Log ("[" + $script:AsgardStep + "/3] " + $title)
    Write-Host "  " -NoNewline
    Write-Part ("[" + $script:AsgardStep + "/3]") 'step' -NoNewline
    Write-Host " " -NoNewline
    Write-Part $title 'head'
}

# -- banner ---------------------------------------------------------------------------------------
# Get-BannerVersion - best effort, exactly install.sh's ladder: pinned env -> a local checkout ->
# __init__.py on main. Never throws and never blocks for long: the banner is decoration, and a dead
# network must cost the install five seconds, not the install.
function Get-BannerVersion {
    if ($env:ASGARD_VERSION) { return $env:ASGARD_VERSION }
    if ($env:ASGARD_INSTALL_SPEC) {
        try {
            $local = Join-Path $env:ASGARD_INSTALL_SPEC 'src\asgard\__init__.py'
            if (Test-Path $local) {
                $m = [regex]::Match((Get-Content $local -Raw), '__version__\s*=\s*"([^"]+)"')
                if ($m.Success) { return $m.Groups[1].Value }
            }
        } catch { }
    }
    try {
        $url = 'https://raw.githubusercontent.com/' + $AsgardRepoSlug + '/main/src/asgard/__init__.py'
        $body = Invoke-RestMethod -Uri $url -UseBasicParsing -TimeoutSec 5
        $m = [regex]::Match([string]$body, '__version__\s*=\s*"([^"]+)"')
        if ($m.Success) { return $m.Groups[1].Value }
    } catch { }
    return ''
}

# Write-VersionLine - dim (vX.Y.Z), right-aligned so it sits under the wordmark. No-op when unknown.
function Write-VersionLine ($version, $width) {
    if (-not $version) { return }
    $tag = '(v' + $version + ')'
    $pad = $width - $tag.Length
    if ($pad -lt 2) { $pad = 2 }
    Write-Part ((' ' * $pad) + $tag) 'dim'
}

function Write-Banner {
    Write-Host ""
    $width = $script:AsgardWordmarkWidth
    $drawn = $false
    if ($script:AsgardRich) {
        $art = ''
        try { $art = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(($script:AsgardLogo -join ''))) } catch { $art = '' }
        if ($art) {
            foreach ($line in ($art -split "`n")) { Write-Part ($line.TrimEnd()) 'head' }
            $width = $script:AsgardLogoWidth
            $drawn = $true
        }
    }
    if (-not $drawn) { foreach ($line in $script:AsgardWordmark) { Write-Part $line 'head' } }
    # The version is fetched AFTER the art is on screen: something appears instantly even when the
    # lookup is waiting on a network that will never answer.
    Write-VersionLine (Get-BannerVersion) $width
    Write-Part ("  " + (Get-Glyph 'info') + " make anything, your way") 'dim'
    Write-Host ""
}

# -- activity - the spinner ------------------------------------------------------------------------
# Clear-SpinLine / Write-SpinFrame - install.sh's `spin`, in PowerShell. The frame is redrawn in
# place with a carriage return; the line is padded to the console width every frame so a shrinking
# label cannot leave debris behind, and it is wiped entirely before the caller prints its own mark.
function Clear-SpinLine {
    if (-not $script:AsgardAnim) { return }
    $w = (Get-ConsoleWidth) - 1
    Write-Host (([string][char]13) + (' ' * $w) + ([string][char]13)) -NoNewline
}

function Write-SpinFrame ($label, $index, $started) {
    $frames = $script:AsgardGlyph['spin']
    $frame = [string]$frames[$index % $frames.Count]
    $tail = ''
    try {
        $secs = [int]((Get-Date) - $started).TotalSeconds
        if ($secs -ge 1) { $tail = ' ' + (Get-Glyph 'info') + ' ' + $secs + 's' }
    } catch { $tail = '' }
    $width = Get-ConsoleWidth
    $budget = $width - 5 - $tail.Length
    if ($budget -lt 10) { $budget = 10 }
    $text = [string]$label
    if ($text.Length -gt $budget) { $text = $text.Substring(0, $budget - 1) + '.' }
    Write-Host (([string][char]13) + '  ') -NoNewline
    Write-Part $frame 'step' -NoNewline
    Write-Host (' ' + $text) -NoNewline
    if ($tail) { Write-Part $tail 'dim' -NoNewline }
    $pad = $width - 1 - (3 + 1 + $text.Length + $tail.Length)
    if ($pad -gt 0) { Write-Host (' ' * $pad) -NoNewline }
}

# -- process helpers ---------------------------------------------------------------------------
function Test-Cmd ($name) {
    $c = Get-Command $name -ErrorAction SilentlyContinue
    if ($c) { return $true }
    return $false
}

# Format-NativeArg - one argument, quoted the way CommandLineToArgvW will read it back.
# Start-Process takes an ARRAY but joins it into one command line with a plain space and no quoting
# of its own, so an argument holding a space arrives at the child split in two. Measured here on
# `sh -c 'sleep 2; echo hi'`, which reached the child as four arguments. The install's own arguments
# happen to be space-free today except the install source - and `C:\Users\Jane Doe\asgard` is an
# ordinary place to keep a checkout.
function Format-NativeArg ($value) {
    $s = [string]$value
    if ($s -ne '' -and -not ($s -match '[\s"]')) { return $s }
    $out = '"'
    $slashes = 0
    foreach ($ch in $s.ToCharArray()) {
        if ($ch -eq '\') { $slashes++; continue }
        if ($ch -eq '"') {
            # Backslashes are literal unless they run into a quote, where each one must be doubled
            # and the quote itself escaped - otherwise the child sees the quote as a delimiter.
            $out += ('\' * ($slashes * 2 + 1)) + '"'
        } else {
            $out += ('\' * $slashes) + $ch
        }
        $slashes = 0
    }
    return $out + ('\' * ($slashes * 2)) + '"'
}

# Resolve-Exe - Start-Process wants a program, not a shell name. Get-Command can answer with an alias
# or several matches; the first Application's own path is the unambiguous thing to launch.
function Resolve-Exe ($name) {
    try {
        $matched = @(Get-Command $name -ErrorAction SilentlyContinue)
        foreach ($c in $matched) { if ($c.CommandType -eq 'Application' -and $c.Source) { return $c.Source } }
    } catch { }
    return $name
}

# Invoke-Spun <file> <args> <label> - run an executable while a spinner turns beside <label>, and
# report by exit code. Output goes to two temp FILES rather than a pipe: a pipe would have to be
# drained on this thread, which is the thread drawing the animation, and a full pipe buffer would
# deadlock a long download. Start-Process is the only launcher in Windows PowerShell that redirects
# to a file, and splatting keeps it correct for a command with no arguments at all.
function Invoke-Spun ($File, $Arguments, $Label) {
    $outFile = [IO.Path]::GetTempFileName()
    $errFile = [IO.Path]::GetTempFileName()
    $lines = New-Object System.Collections.ArrayList
    $code = 9009
    try {
        $sp = @{
            FilePath = (Resolve-Exe $File); NoNewWindow = $true; PassThru = $true
            RedirectStandardOutput = $outFile; RedirectStandardError = $errFile
        }
        if ($Arguments -and $Arguments.Count -gt 0) {
            $quoted = @()
            foreach ($a in $Arguments) { $quoted += (Format-NativeArg $a) }
            $sp['ArgumentList'] = $quoted
        }
        $proc = Start-Process @sp
        $started = Get-Date
        $i = 0
        while (-not $proc.HasExited) {
            Write-SpinFrame $Label $i $started
            $i++
            Start-Sleep -Milliseconds 80
        }
        $proc.WaitForExit()
        $code = $proc.ExitCode
        if ($null -eq $code) { $code = 0 }
    } catch {
        [void]$lines.Add($_.Exception.Message)
        $code = 9009
    } finally {
        Clear-SpinLine
    }
    foreach ($f in @($outFile, $errFile)) {
        try {
            if (Test-Path $f) {
                foreach ($line in (Get-Content -Path $f -ErrorAction SilentlyContinue)) {
                    if ($line) { [void]$lines.Add([string]$line) }
                }
            }
        } catch { }
        try { Remove-Item $f -Force -ErrorAction SilentlyContinue } catch { }
    }
    foreach ($line in $lines) { Add-Log ("      | " + $line) }
    return (New-Object psobject -Property @{ Code = $code; Output = ($lines -join [Environment]::NewLine) })
}

# Invoke-Native <file> <args> - run an executable and report by exit code, never by exception.
# $ErrorActionPreference is forced to 'Continue' for the call: with 'Stop' in effect, Windows
# PowerShell converts a native command's redirected stderr into a terminating NativeCommandError,
# and tools like uv write ordinary progress there. Returns @{ Code; Output }.
# -Spin <label> animates the wait instead of scrolling the tool's output past the user. Where no
# animation is possible (redirected output, NO_COLOR, CI) the label is printed as a plain line and
# the output is streamed as before - a log file wants the detail that a screen does not.
function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [string[]]$Arguments = @(),
        [switch]$Quiet,
        [string]$Spin
    )
    if (-not (Test-Cmd $File)) {
        $miss = "'" + $File + "' not found on PATH"
        Add-Log ("      | " + $miss)
        return (New-Object psobject -Property @{ Code = 9009; Output = $miss })
    }
    if ($Spin) {
        if ($script:AsgardAnim) { return (Invoke-Spun $File $Arguments $Spin) }
        Write-Info $Spin
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

# Get-UvVersion - just the number. `uv --version` answers "uv 0.9.2", and the mark line already
# says "uv", so printing the raw output gives "uv uv 0.9.2". install.sh takes the same second field.
function Get-UvVersion {
    $r = Invoke-Native 'uv' @('--version') -Quiet
    $text = ([string]$r.Output).Trim()
    $parts = $text -split '\s+'
    if ($parts.Count -ge 2) { return $parts[1] }
    return $text
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
    Write-Part ("  " + $prompt) 'dim'
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
    # The terminal's own capability, because "the installer printed boxes" and "the installer printed
    # nothing while it worked" are both answered by this row and by nothing else in the report.
    try {
        $caps = 'ascii'
        if ($script:AsgardRich) { $caps = 'unicode' }
        $vt = 'no-vt'
        if ($script:AsgardVT) { $vt = 'vt' }
        $term = $env:WT_SESSION
        if ($term) { $term = 'windows-terminal' } else { $term = $env:TERM_PROGRAM }
        if (-not $term) { $term = 'console' }
        [void]$rows.Add("terminal      " + $term + " (" + $caps + ", " + $vt + ")")
    } catch { }
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

    Clear-SpinLine
    Write-Host ""
    Write-Part ("  " + (Get-Glyph 'fail') + "  " + $msg) 'fail'
    Add-Log ("  X  " + $msg)
    if (-not $expected) {
        # Unexpected crash - the position block is the only thing that says which line died.
        Add-Log $where
        if ($where) { Write-Part $where 'dim' }
        Add-Hint 'This one is a bug in the installer, not in your machine. Please report the log below.'
    }
    if ($script:AsgardHints.Count -gt 0) {
        Write-Host ""
        Write-Part "  try:" 'head'
        foreach ($h in $script:AsgardHints) { Add-Log ("   -> " + $h); Write-Part ("   -> " + $h) 'dim' }
    }
    Write-Host ""
    Write-Part "  environment:" 'head'
    foreach ($row in (Get-EnvReport)) { Add-Log ("     " + $row); Write-Part ("     " + $row) 'dim' }
    $log = Save-Transcript
    if ($log) {
        Write-Host ""
        Write-Part ("  full log: " + $log) 'dim'
    }
}

# -- install steps -----------------------------------------------------------------------------
# Run-once: this is called before the banner (whose version lookup is the FIRST https request the
# script makes - on 5.1 it would be refused without the line below) and again from preflight, which
# is where a person expects to be told that the host's TLS could not be raised.
$script:AsgardWebReady = $false
function Initialize-Web {
    if ($script:AsgardWebReady) { return }
    $script:AsgardWebReady = $true
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
        $null = Invoke-Native $ps @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-NonInteractive', '-EncodedCommand', $enc) -Spin 'bootstrapping uv...'
        Update-PathFromEnvironment
        if (Test-Cmd 'uv') { return $true }
    } else {
        Add-Hint 'no powershell.exe or pwsh.exe was found to host the uv installer'
    }
    if (Test-Cmd 'winget') {
        $wingetArgs = @('install', '--id', 'astral-sh.uv', '-e', '--source', 'winget')
        $wingetArgs += @('--accept-package-agreements', '--accept-source-agreements')
        $null = Invoke-Native 'winget' $wingetArgs -Spin 'uv via winget...'
        Update-PathFromEnvironment
        if (Test-Cmd 'uv') { return $true }
    }
    foreach ($py in @('py', 'python', 'python3')) {
        if (-not (Test-Cmd $py)) { continue }
        $pyArgs = @('-m', 'pip', 'install', '--user', '--upgrade', 'uv')
        if ($py -eq 'py') { $pyArgs = @('-3') + $pyArgs }
        $null = Invoke-Native $py $pyArgs -Spin ("uv via " + $py + " -m pip...")
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
    Phase ("preflight " + (Get-Glyph 'sep') + " check environment")
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        Add-Hint 'Windows PowerShell 5.1 ships with Windows 10/11 and Server 2016+; older hosts can install PowerShell 7 from https://aka.ms/powershell'
        Fail ("this installer needs PowerShell 5.1 or newer - this is " + $PSVersionTable.PSVersion)
    }
    Write-Ok "powershell" ([string]$PSVersionTable.PSVersion)
    $arch = $env:PROCESSOR_ARCHITECTURE
    if (-not $arch) { $arch = 'unknown' }
    Write-Ok "platform" ("Windows/" + $arch.ToLowerInvariant())
    Initialize-Web

    $haveUv = Test-Cmd 'uv'
    if ($haveUv) {
        Write-Ok "uv" ((Get-UvVersion) + " (already installed)")
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
    if ($pyLine) { Write-Ok $pyLine "(not required - uv brings its own)" }
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
        if ([int]$Matches[1] -ge 22) { Write-Ok "node" ($nodeV + " (design engines)") }
        else { Write-Warn2 ("node " + $nodeV + " - Freyja design engines need >= 22. Upgrade: winget install OpenJS.NodeJS.LTS (or https://nodejs.org)") }
    } else {
        Write-Warn2 "node not found - Freyja design engines (detector/hooks/live) need node >= 22. Install: winget install OpenJS.NodeJS.LTS (or https://nodejs.org). Asgard installs fine without it."
    }
    return $haveUv
}

function Main {
    Initialize-Terminal
    Initialize-Web   # before the banner: its version lookup is this script's first https request
    Write-Banner

    $haveUv = Invoke-Preflight

    # -- [2/3] install --
    Phase ("install " + (Get-Glyph 'sep') + " toolchain + asgard")
    if (-not $haveUv) {
        if (-not (Install-Uv)) {
            Add-Hint 'install uv by hand, then re-run this script: https://docs.astral.sh/uv/getting-started/installation/'
            Add-Hint 'on a managed network, set HTTPS_PROXY before re-running'
            Add-Hint 'if uv did install, open a NEW terminal so PATH picks it up'
            Fail "uv bootstrap failed - every method above was tried"
        }
        Write-Ok "uv" (Get-UvVersion)
    }

    # Best-effort: uv downloads the interpreter on demand at install time anyway. Reported honestly
    # either way - the old script printed "OK python 3.14" even when this step had failed.
    $r = Invoke-Native 'uv' @('python', 'install', '3.14') -Spin 'preparing python 3.14...'
    if ($r.Code -eq 0) {
        Write-Ok "python" "3.14"
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
    $r = Invoke-Native 'uv' @('tool', 'install', '--force', '--python', '3.14', $from) -Spin ("installing asgard (" + $desc + ")...")
    if ($r.Code -ne 0) {
        Add-Hint 'the uv output above carries the real reason (network, proxy, or a bad version pin)'
        Add-Hint 'pin a known-good version and retry: $env:ASGARD_VERSION = "X.Y.Z"'
        Fail ("install failed (uv exit " + $r.Code + "): " + $from)
    }
    $null = Invoke-Native 'uv' @('tool', 'update-shell') -Quiet
    Update-PathFromEnvironment
    Write-Ok "asgard" "linked (uv tool)"

    # -- [3/3] verify --
    Phase ("verify " + (Get-Glyph 'sep') + " check install")
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
    if ($cmd) { Write-Ok "on PATH" $cmd.Source }
    else { Write-Warn2 "not on PATH yet - restart the terminal (or run: uv tool update-shell)" }

    # Memory search model - fetch it here. Skipping it means the user meets a ~45s download
    # in the middle of real work the first time memory runs. Waiting belongs in the install.
    # Failure is a warning only: without the model, search still runs on the lexical path.
    # $exe, not the bare name: on a shell whose PATH has not been reloaded the bare name is a
    # 9009, and the user would be told the model was skipped when nothing had even been tried.
    $r = Invoke-Native $exe @('memory', 'semantic', 'warmup') -Spin 'fetching memory search model (~1GB, once)...'
    if ($r.Code -eq 0) { Write-Ok "memory search" "semantic model ready" }
    else { Write-Warn2 "memory search model skipped - lexical search works; retry: asgard memory semantic warmup" }

    Write-Host ""
    Write-Host "  " -NoNewline
    Write-Part ((Get-Glyph 'ok') + " installed") 'ok' -NoNewline
    Write-Host " - next:"
    Write-Host "    " -NoNewline
    Write-Part "asgard doctor" 'strong' -NoNewline
    Write-Host "   " -NoNewline
    Write-Part "# verify" 'dim'
    Write-Host "    " -NoNewline
    Write-Part "asgard --help" 'strong'
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
Restore-Terminal
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
