param([string]$Profile = 'web')
$ErrorActionPreference = 'Stop'
$pluginDirectory = Split-Path -Parent $PSCommandPath
foreach ($requiredCommand in @('node', 'npm', 'python', 'uv', 'tar')) {
    if (-not (Get-Command $requiredCommand -ErrorAction SilentlyContinue)) {
        throw "Missing dependency: $requiredCommand. See README.md for installation instructions."
    }
}
$nodeMajor = [int]((& node -p 'parseInt(process.versions.node)') | Select-Object -First 1)
if ($nodeMajor -lt 22) { throw 'Node.js 22 or newer is required.' }
Push-Location -LiteralPath $pluginDirectory
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed: $LASTEXITCODE" }
    & node scripts/install.mjs $Profile
    if ($LASTEXITCODE -ne 0) { throw "Plugin installation failed: $LASTEXITCODE" }
} finally { Pop-Location }
