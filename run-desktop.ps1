#Requires -Version 5.1
<#
  Starts Ade Desktop (the PySide6 app) detached, so it outlives this shell.

    .\run-desktop.ps1           start it -- or, if it is running, bring it forward
    .\run-desktop.ps1 -Status   report whether it is up
    .\run-desktop.ps1 -Stop     stop it

  A venv's pythonw.exe is only a redirector: it starts the base interpreter
  as a CHILD and waits. -Status reports the child (the process actually
  running the app); -Stop stops the child, then the redirector. Stopping
  only the redirector would leave the app running with no parent.
#>
[CmdletBinding()]
param(
  [switch]$Status,
  [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $here '.venv'
$pythonw = Join-Path $venv 'Scripts\pythonw.exe'

$scripts = Join-Path $venv 'Scripts'

function Test-UnderVenv($path) {
  return [bool]($path -and $path.StartsWith($venv, [StringComparison]::OrdinalIgnoreCase))
}

# Both processes are found by their OWN command line, which names this
# venv's Scripts\ directory and `-m ade_desktop` -- the redirector's and the
# child's are identical (measured on the live app, 2026-09-17). Never by
# ParentProcessId alone: Windows reuses PIDs, and a process whose parent has
# died keeps the dead PID. That day explorer.exe on this machine was the
# "child" of a dead PID, and a launcher that happened to get that PID would
# have had -Stop force-kill Explorer. Matching by command line also finds an
# app whose launcher has died.
function Get-AppProcs {
  $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.CommandLine -and
      $_.CommandLine.IndexOf($scripts, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
      $_.CommandLine -like '*-m ade_desktop*' -and
      $_.CommandLine -notlike '*--smoke*'
    })
  $parents = @($all | Where-Object { Test-UnderVenv $_.ExecutablePath })
  $children = @($all | Where-Object { -not (Test-UnderVenv $_.ExecutablePath) })
  return [pscustomobject]@{ Children = $children; Parents = $parents }
}

if ($Status) {
  $p = Get-AppProcs
  if ($p.Children.Count -gt 0) {
    "desktop: running (pid $(($p.Children | ForEach-Object { $_.ProcessId }) -join ', '))"
  } elseif ($p.Parents.Count -gt 0) {
    "desktop: starting or wedged (redirector pid $(($p.Parents | ForEach-Object { $_.ProcessId }) -join ', '), no child yet)"
  } else {
    'desktop: not running'
  }
  return
}

if ($Stop) {
  $p = Get-AppProcs
  if ($p.Children.Count -eq 0 -and $p.Parents.Count -eq 0) {
    'desktop: not running'
    return
  }
  $stopped = @()
  foreach ($proc in @($p.Children) + @($p.Parents)) {
    if ($proc) {
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
      $stopped += $proc.ProcessId
    }
  }
  "desktop: stopped ($($stopped -join ', '))"
  return
}

if (-not (Test-Path $pythonw)) {
  throw ("No venv at $venv. Set it up once:`n" +
         "  py -V:Astral/CPython3.14.0 -m venv `"$venv`"`n" +
         "  & `"$venv\Scripts\python.exe`" -m pip install -r `"$here\requirements.txt`"")
}

# Launched even when already running: the new process hands "show" to the
# running one over the single-instance pipe and exits. Start-Process gives
# it its own process group, which is how run-avatar.ps1 outlives its shell.
Start-Process -FilePath $pythonw -ArgumentList '-m', 'ade_desktop' -WorkingDirectory $here -WindowStyle Hidden
'desktop: launched (a running instance is brought forward instead)'
