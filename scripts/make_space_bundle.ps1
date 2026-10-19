<#
.SYNOPSIS
  Export the COMMITTED files of HEAD into a temp folder, ready to push to a Hugging Face Space.

.DESCRIPTION
  - Uses `git archive HEAD`, so only committed files are exported. Uncommitted edits, untracked
    files, .env and ignored files are never included.
  - Drops eval/, docs/screenshots and .claude from the copy (not needed to build the image).
  - Prepends the Space front matter (sdk: docker, app_port: 7860) to the COPY's README.md. The
    repository's own README is not touched.
  - Refuses to continue if the copy contains a .env file or a database.
  - Prints the folder path and the file count.

  It only runs read-only git commands (rev-parse, status, archive). It does not init a repository,
  touch remotes or push. The output folder is outside the repository.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\make_space_bundle.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repo = (& git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repo) { throw 'Not inside a git repository.' }
$repo = (Resolve-Path $repo).Path

& git -C $repo rev-parse --verify HEAD | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'The repository has no commits.' }
$head = (& git -C $repo rev-parse --short HEAD).Trim()

$dirty = & git -C $repo status --porcelain --untracked-files=no
if ($dirty) {
    Write-Warning 'Tracked files have uncommitted changes. They are NOT in the bundle (HEAD only).'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path ([IO.Path]::GetTempPath()) "tribunal-space-$stamp"
if ($out.StartsWith($repo, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to write inside the repository: $out"
}
New-Item -ItemType Directory -Path $out | Out-Null

# A zip avoids PowerShell 5.1 corrupting binary data piped between native commands.
$zip = Join-Path ([IO.Path]::GetTempPath()) "tribunal-space-$stamp.zip"
try {
    & git -C $repo archive --format=zip -o $zip HEAD
    if ($LASTEXITCODE -ne 0) { throw 'git archive failed.' }
    Expand-Archive -LiteralPath $zip -DestinationPath $out
} finally {
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
}

# Not needed to build the image (and eval/ holds datasets and result files).
foreach ($rel in 'eval', 'docs\screenshots', '.claude') {
    $p = Join-Path $out $rel
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
}

# Safety net: a committed secret or database must stop the export.
$bad = Get-ChildItem -LiteralPath $out -Recurse -Force -File |
    Where-Object { $_.Name -match '^\.env($|\.)' -and $_.Name -ne '.env.example' -or $_.Name -match '\.db(-.*)?$' }
if ($bad) {
    $bad | ForEach-Object { Write-Error "Unexpected file in the bundle: $($_.FullName)" }
    throw 'Bundle contains a .env file or a database. Delete the folder and fix the repository.'
}

# Space front matter, written to the COPY's README only (UTF-8 without BOM, LF).
$readme = Join-Path $out 'README.md'
if (-not (Test-Path -LiteralPath $readme)) { throw 'README.md is missing from HEAD.' }
$utf8 = New-Object System.Text.UTF8Encoding($false)
$current = [IO.File]::ReadAllText($readme, $utf8)
if ($current.TrimStart().StartsWith('---')) { throw 'README.md already has front matter.' }
$emoji = [string][char]0x2696 + [char]0xFE0F   # the scales emoji, built from code points
$front = @(
    '---'
    'title: Tribunal'
    "emoji: $emoji"
    'colorFrom: gray'
    'colorTo: yellow'
    'sdk: docker'
    'app_port: 7860'
    'pinned: false'
    '---'
    ''
) -join "`n"
[IO.File]::WriteAllText($readme, $front + "`n" + $current, $utf8)

$count = (Get-ChildItem -LiteralPath $out -Recurse -Force -File | Measure-Object).Count
Write-Host ''
Write-Host "Bundle of commit $head"
Write-Host "Folder:     $out"
Write-Host "File count: $count"
Write-Host ''
Write-Host 'Review it before pushing anywhere (see docs/DEPLOY.md).'
