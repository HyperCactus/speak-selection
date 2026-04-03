$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$scriptPath = Join-Path $projectRoot "speak-selection.py"

$pythonExe = $null
$pythonPrefixArgs = @()
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    $pythonExe = $venvPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonExe = "py"
    $pythonPrefixArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = "python"
} else {
    Write-Error "Python was not found. Install Python 3 and try again."
    exit 1
}

if ($args.Count -gt 0) {
    $invokeArgs = $pythonPrefixArgs + @($scriptPath) + $args
    & $pythonExe @invokeArgs
    exit $LASTEXITCODE
}

$selectedText = ""
$clipboardBefore = $null

try {
    $clipboardBefore = Get-Clipboard -Raw
} catch {
}

try {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.SendKeys]::SendWait("^c")
    Start-Sleep -Milliseconds 120
    $selectedText = Get-Clipboard -Raw
} catch {
    if (-not [string]::IsNullOrWhiteSpace($clipboardBefore)) {
        $selectedText = $clipboardBefore
    }
}

if ($clipboardBefore -ne $null) {
    try {
        Set-Clipboard -Value $clipboardBefore
    } catch {
    }
}

if ([string]::IsNullOrWhiteSpace($selectedText)) {
    exit 0
}

$invokeArgs = $pythonPrefixArgs + @($scriptPath, "--text", $selectedText)
& $pythonExe @invokeArgs
exit $LASTEXITCODE
