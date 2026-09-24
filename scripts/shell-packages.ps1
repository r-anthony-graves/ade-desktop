<#
.SYNOPSIS
  Install and VERIFY the shell's advanced packages. Requirement 9's install
  half (Ray, 2026-09-24).

.DESCRIPTION
  Run BY HAND, never by the app. Idempotent: anything already present is
  skipped, not reinstalled.

  winget only. Measured on this box 2026-09-24: winget is present, scoop and
  choco are not, so a fallback chain would be untested code pretending to be
  a safety net.

  It VERIFIES with Get-Command / Get-Module rather than trusting an
  installer's exit code -- winget returns 0 for "already installed", for
  "installed but not on PATH until a new shell", and for several partial
  states, so its exit code does not answer the only question that matters:
  can you actually run the thing afterwards.

  The capability half of requirement 9 lives in the app, not here: the
  terminal handles 24-bit colour, the alternate screen and interactive TUIs,
  so whatever is installed below works properly once installed.

.PARAMETER WhatIfOnly
  List what would be installed and change nothing.

.EXAMPLE
  pwsh -File scripts\shell-packages.ps1 -WhatIfOnly
  pwsh -File scripts\shell-packages.ps1
#>
[CmdletBinding()]
param([switch]$WhatIfOnly)

$ErrorActionPreference = 'Continue'

# name -> winget package id.
# Already present on this box 2026-09-24 and therefore absent from this
# list: git, rg (BurntSushi.ripgrep.MSVC), gh.
$Tools = [ordered]@{
    'fzf'        = 'junegunn.fzf'
    'bat'        = 'sharkdp.bat'
    'eza'        = 'eza-community.eza'
    'jq'         = 'jqlang.jq'
    'delta'      = 'dandavison.delta'
    'oh-my-posh' = 'JanDeDobbeleer.OhMyPosh'
    'nvim'       = 'Neovim.Neovim'
}

# PSReadLine ships with pwsh 7 and is already present.
$Modules = @('posh-git', 'Terminal-Icons', 'z', 'PSFzf')

function Test-Tool([string]$Name) {
    [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-Mod([string]$Name) {
    [bool](Get-Module -ListAvailable -Name $Name -ErrorAction SilentlyContinue)
}

function Sync-Path {
    # A freshly installed tool's PATH entry is not visible to THIS process.
    # Without this the verification pass calls every new install a failure.
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') +
                ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
}

if (-not (Test-Tool 'winget')) {
    Write-Error 'winget is not available, so nothing can be installed. Install App Installer from the Microsoft Store.'
    exit 1
}

$report = @()

foreach ($name in $Tools.Keys) {
    if (Test-Tool $name) {
        $report += [pscustomobject]@{ Name = $name; Kind = 'tool'; Before = $true; After = $true; Action = 'skipped' }
        Write-Host "skip     $name (already present)"
        continue
    }
    if ($WhatIfOnly) {
        $report += [pscustomobject]@{ Name = $name; Kind = 'tool'; Before = $false; After = $false; Action = 'would install' }
        Write-Host "would    install $name ($($Tools[$name]))"
        continue
    }
    Write-Host "install  $name ($($Tools[$name]))"
    winget install --id $Tools[$name] -e --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
    Sync-Path
    $after = Test-Tool $name
    $report += [pscustomobject]@{ Name = $name; Kind = 'tool'; Before = $false; After = $after
                                  Action = $(if ($after) { 'installed' } else { 'FAILED' }) }
}

foreach ($name in $Modules) {
    if (Test-Mod $name) {
        $report += [pscustomobject]@{ Name = $name; Kind = 'module'; Before = $true; After = $true; Action = 'skipped' }
        Write-Host "skip     $name (already present)"
        continue
    }
    if ($WhatIfOnly) {
        $report += [pscustomobject]@{ Name = $name; Kind = 'module'; Before = $false; After = $false; Action = 'would install' }
        Write-Host "would    install module $name"
        continue
    }
    Write-Host "install  module $name"
    Install-Module -Name $name -Scope CurrentUser -Force -AcceptLicense -ErrorAction Continue
    $after = Test-Mod $name
    $report += [pscustomobject]@{ Name = $name; Kind = 'module'; Before = $false; After = $after
                                  Action = $(if ($after) { 'installed' } else { 'FAILED' }) }
}

''
'--- verification: what is ACTUALLY reachable now, not what the installer claimed ---'
$report | Format-Table Name, Kind, Before, After, Action -AutoSize

$failed = @($report | Where-Object { $_.Action -eq 'FAILED' })
if ($failed.Count) {
    Write-Warning "$($failed.Count) did not verify: $($failed.Name -join ', ')"
    Write-Warning 'A tool installed into a new PATH entry can need a fresh shell. Re-run this script to confirm.'
    exit 1
}
'all verified'
