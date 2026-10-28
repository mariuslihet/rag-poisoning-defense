param(
    [ValidateSet('dashboard', 'demo', 'local')]
    [string]$Mode = 'dashboard',
    [ValidateSet('strict', 'sanitize')]
    [string]$Policy = 'strict',
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$spadesPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $spadesPython)) {
    $spadesPythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($spadesPythonCommand) {
        $spadesPython = $spadesPythonCommand.Source
    } else {
        $spadesPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    }
}
if (-not (Test-Path -LiteralPath $spadesPython)) {
    throw 'Python 3.10 or newer is required. Install Python and run this launcher again.'
}
if ($Mode -ne 'dashboard') {
    $spadesProfile = if ($Mode -eq 'demo') { 'foundation' } else { 'complex' }
    $spadesDepth = if ($Mode -eq 'demo') { 5 } else { 20 }
    & $spadesPython -m spades run --mode $Mode --profile $spadesProfile --k $spadesDepth --policy $Policy --output "output/$Mode-$Policy-$spadesProfile"
    if ($LASTEXITCODE -ne 0) {
        throw 'The experiment did not complete successfully. Review the error above.'
    }
}
Write-Host "Open http://127.0.0.1:$Port to view Spades. Press Ctrl+C to stop."
& $spadesPython -m spades serve --output output --port $Port
