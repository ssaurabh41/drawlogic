# Check that this copy of drawlogic has the files it should, on Windows.
#
#   powershell -ExecutionPolicy Bypass -File verify.ps1
#
# Run it from the folder that contains manifest.txt -- the top of the repo --
# or point it anywhere with -Root. It reads manifest.txt, hashes each file it
# names, and reports MATCH (with the file's size), MISMATCH, MISSING or EXTRA.
#
# Line endings and trailing blank lines are made uniform before hashing,
# exactly as drawlogic/cli.py does it, so a file is only "wrong" when what it
# says is different. Git rewrites line endings on checkout by default on
# Windows, and a byte-for-byte check reports every file in a perfectly good
# clone as broken -- which is what happened the first time one of these was
# handed over: all 28 files "mismatched" and not one of them actually
# different. Copying a file by hand from a browser has the same effect on the
# newline at the end of the file. A checker that cries wolf is worse than
# none, because the next real mismatch gets ignored too.
#
# Works on Windows PowerShell 5.1 and on PowerShell 7+.

[CmdletBinding()]
param(
    [string]$Root = $PSScriptRoot,
    [string]$Manifest
)

$ErrorActionPreference = 'Stop'

if (-not $Root) { $Root = (Get-Location).Path }
# Resolved once, so the relative paths worked out below cannot be thrown off
# by a trailing separator or by how the folder was spelled on the way in.
$Root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\', '/')
if (-not $Manifest) { $Manifest = Join-Path $Root 'manifest.txt' }

if (-not (Test-Path -LiteralPath $Manifest)) {
    Write-Host "No manifest.txt at $Manifest" -ForegroundColor Red
    Write-Host "Run this from the top of the drawlogic folder, or pass -Root."
    exit 2
}

# UTF-8 without a byte order mark, which is what File.ReadAllText writes back
# out and what the Python side hashes.
$utf8 = New-Object System.Text.UTF8Encoding($false)
$sha = [System.Security.Cryptography.SHA256]::Create()

function Get-ContentHash([string]$Path) {
    # ReadAllText with a UTF-8 encoding strips a byte order mark if there is
    # one, so a file saved by Notepad hashes the same as one saved by anything
    # else.
    $text = [System.IO.File]::ReadAllText($Path, $utf8)
    $text = $text -replace "`r`n", "`n"
    $text = $text -replace "`r", "`n"
    # A file pasted by hand from a browser routinely gains or loses the
    # newline at the very end without anything else having changed, so one
    # trailing newline hashes the same as none or several -- exactly as
    # drawlogic/cli.py does it.
    $text = $text.TrimEnd("`n")
    if ($text.Length -gt 0) { $text = $text + "`n" }
    $bytes = $utf8.GetBytes($text)
    return ([System.BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
}

$ok = 0
$bad = New-Object System.Collections.ArrayList
$listed = New-Object System.Collections.Generic.HashSet[string]

foreach ($line in Get-Content -LiteralPath $Manifest) {
    $line = $line.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    if ($line -notmatch '^([0-9a-fA-F]{64})\s+(.+)$') { continue }

    $expected = $Matches[1].ToLowerInvariant()
    $relative = $Matches[2].Trim()
    [void]$listed.Add($relative)

    # Forward slashes as the manifest writes them: .NET accepts them on
    # Windows too, so there is nothing to translate and nothing to get wrong.
    $full = Join-Path $Root $relative
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        Write-Host "MISSING   $relative" -ForegroundColor Red
        [void]$bad.Add($relative)
        continue
    }

    try {
        $actual = Get-ContentHash $full
    } catch {
        Write-Host "UNREADABLE $relative -- $($_.Exception.Message)" -ForegroundColor Red
        [void]$bad.Add($relative)
        continue
    }

    if ($actual -eq $expected) {
        $ok++
        # The size is of the file as it sits on disk, not of the normalised
        # text that was hashed -- it is here so a MATCH still says something
        # concrete about the file, the same way MISMATCH names the file that
        # differs rather than just counting it.
        $size = (Get-Item -LiteralPath $full).Length
        Write-Host ("MATCH     {0}  ({1:N0} bytes)" -f $relative, $size) -ForegroundColor Green
    } else {
        Write-Host "MISMATCH  $relative" -ForegroundColor Yellow
        [void]$bad.Add($relative)
    }
}

# A file the manifest has never heard of is worth saying so: it is usually a
# leftover from an older version that Python will happily import instead of
# the one meant to be there.
$package = Join-Path $Root 'drawlogic'
if (Test-Path -LiteralPath $package) {
    $prefix = $Root + [System.IO.Path]::DirectorySeparatorChar
    foreach ($file in Get-ChildItem -LiteralPath $package -Recurse -File) {
        if ($file.Extension -eq '.pyc' -or $file.Extension -eq '.pyo') { continue }
        if ($file.FullName -like '*__pycache__*') { continue }
        if (-not $file.FullName.StartsWith($prefix)) { continue }
        $relative = $file.FullName.Substring($prefix.Length) -replace '\\', '/'
        if (-not $listed.Contains($relative)) {
            Write-Host "EXTRA     $relative" -ForegroundColor Yellow
            [void]$bad.Add($relative)
        }
    }
}

Write-Host ""
if ($bad.Count -eq 0) {
    Write-Host "$ok files, all as they should be" -ForegroundColor Cyan
    exit 0
}

Write-Host "$ok files as they should be, $($bad.Count) not" -ForegroundColor Cyan
Write-Host ""
Write-Host "Files from different versions of drawlogic cannot work together."
Write-Host "Take the whole repository at once rather than file by file:"
Write-Host "  git clone https://github.com/ssaurabh41/drawlogic"
Write-Host "or download and unzip"
Write-Host "  https://github.com/ssaurabh41/drawlogic/archive/refs/heads/main.zip"
exit 1
