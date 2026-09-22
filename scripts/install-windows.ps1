#requires -Version 5.1
[CmdletBinding()]
param([switch]$NoLaunch)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:MeetingbotRoot = Split-Path -Parent $PSScriptRoot

function Update-MeetingbotPath {
    # Keep caller-specific tools (for example a Node version manager), then add
    # changes made by installers without requiring a new terminal.
    $paths = @($env:Path)
    $paths += [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $paths += [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($env:LOCALAPPDATA) { $paths += Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links' }
    if ($env:ProgramFiles) { $paths += Join-Path $env:ProgramFiles 'WinGet\Links' }
    $env:Path = (($paths -join ';').Split(';') | Where-Object { $_ } |
        ForEach-Object { [Environment]::ExpandEnvironmentVariables($_) } |
        Select-Object -Unique) -join ';'
}

function Find-MeetingbotApplication([string]$Name) {
    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    return $null
}

function Assert-MeetingbotWindows {
    $architecture = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $architecture = $env:PROCESSOR_ARCHITEW6432 }
    if ($architecture -ne 'AMD64' -or -not [Environment]::Is64BitOperatingSystem -or
        -not [Environment]::Is64BitProcess) {
        throw 'Meetingbot requires Windows x64 and 64-bit PowerShell. Windows ARM and 32-bit Windows are not supported.'
    }
}

function Find-MeetingbotPython {
    $probe = 'import sys,struct; sys.exit(1) if sys.version_info[:2] != (3,12) or struct.calcsize(chr(80)) != 8 else print(sys.executable)'
    $launcher = Find-MeetingbotApplication 'py.exe'
    if ($launcher) {
        try {
            $result = & $launcher -3.12 -c $probe 2>$null
            if ($LASTEXITCODE -eq 0 -and $result) { return [string]($result | Select-Object -Last 1) }
        } catch { }
    }
    $candidates = @(Find-MeetingbotApplication 'python.exe'; Find-MeetingbotApplication 'python3.exe')
    if ($env:LOCALAPPDATA) { $candidates += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe' }
    if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles 'Python312\python.exe' }
    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        # Windows' empty App Execution Alias opens the Store instead of Python.
        if ($candidate -match '\\Microsoft\\WindowsApps\\python3?\.exe$' -or
            -not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            $result = & $candidate -c $probe 2>$null
            if ($LASTEXITCODE -eq 0 -and $result) { return [string]($result | Select-Object -Last 1) }
        } catch { }
    }
    return $null
}

function Stop-MeetingbotCommand([string]$Message, [int]$Code) {
    $exception = [System.Exception]::new($Message)
    $exception.Data['ExitCode'] = $Code
    throw $exception
}

function Install-MeetingbotDependency([string]$Package, [string[]]$Options = @()) {
    $winget = Find-MeetingbotApplication 'winget.exe'
    if (-not $winget) {
        throw ('Missing dependency: ' + $Package + '. Install App Installer (winget) from Microsoft Store, ' +
            'or install Python 3.12 x64, Node.js 22 and FFmpeg manually, then run Install-Windows.cmd again.')
    }
    Write-Host "Installing $Package with Windows Package Manager..."
    & $winget install --id $Package --exact --source winget --architecture x64 --no-upgrade `
        --accept-source-agreements --accept-package-agreements @Options | Out-Host
    $code = $LASTEXITCODE
    if ($code -ne 0) { Stop-MeetingbotCommand "winget could not install $Package (exit $code)." $code }
    Update-MeetingbotPath
}

function Assert-MeetingbotNode {
    $node = Find-MeetingbotApplication 'node.exe'
    if (-not $node) { return $false }
    $version = & $node --version
    $match = [regex]::Match([string]$version, '^v(\d+)\.')
    if ($LASTEXITCODE -ne 0 -or -not $match.Success) {
        throw 'The existing Node.js installation cannot run. Repair it and run Install-Windows.cmd again.'
    }
    if ([int]$match.Groups[1].Value -lt 22) {
        throw "Node.js $version is already installed. Select Node.js 22 or newer, then retry. Existing Node.js was preserved."
    }
    if (-not (Find-MeetingbotApplication 'npm.cmd')) {
        throw 'Node.js is installed but npm.cmd is missing. Repair Node.js with npm enabled, then retry.'
    }
    return $true
}

function Invoke-MeetingbotWindowsInstall([switch]$SkipLaunch) {
    Assert-MeetingbotWindows
    # Python's redirected stdout must preserve Korean/non-ASCII checkout paths.
    $env:PYTHONUTF8 = '1'
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    Update-MeetingbotPath
    Write-Host 'Meetingbot setup: checking Python, Node.js and FFmpeg. Existing compatible tools will be reused.'
    $python = Find-MeetingbotPython
    if (-not $python) {
        Install-MeetingbotDependency 'Python.Python.3.12' @('--scope', 'user')
        $python = Find-MeetingbotPython
        if (-not $python) { throw 'Python 3.12 x64 could not be found after installation. Reopen Install-Windows.cmd.' }
    }
    if (-not (Assert-MeetingbotNode)) {
        # The MSI includes npm command wrappers; the portable winget package only aliases node.
        Install-MeetingbotDependency 'OpenJS.NodeJS.22' @('--installer-type', 'wix')
        if (-not (Assert-MeetingbotNode)) { throw 'Node.js could not be found after installation. Reopen Install-Windows.cmd.' }
    }
    if (-not (Find-MeetingbotApplication 'ffmpeg.exe') -or -not (Find-MeetingbotApplication 'ffprobe.exe')) {
        Install-MeetingbotDependency 'Gyan.FFmpeg'
        if (-not (Find-MeetingbotApplication 'ffmpeg.exe') -or -not (Find-MeetingbotApplication 'ffprobe.exe')) {
            throw 'FFmpeg and ffprobe must both be on PATH. Reopen Install-Windows.cmd after repairing FFmpeg.'
        }
    }
    $arguments = @((Join-Path $script:MeetingbotRoot 'scripts\install.py'))
    if ($SkipLaunch) { $arguments += '--no-launch' }
    & $python @arguments | Out-Host
    $code = $LASTEXITCODE
    if ($code -ne 0) { Stop-MeetingbotCommand "Meetingbot installation exited with code $code." $code }
}

# Dot-sourcing exposes functions for isolated checks without installing anything.
if ($MyInvocation.InvocationName -ne '.') {
    try {
        Invoke-MeetingbotWindowsInstall -SkipLaunch:$NoLaunch
        exit 0
    } catch {
        Write-Host $_.Exception.Message -ForegroundColor Red
        $code = 1
        if ($_.Exception.Data.Contains('ExitCode')) { $code = [int]$_.Exception.Data['ExitCode'] }
        exit $code
    }
}
