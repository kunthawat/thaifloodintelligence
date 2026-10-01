param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$pgBin = Join-Path $root 'local_runtime\pgsql\bin'
$pgData = Join-Path $root 'local_runtime\pgdata'
$python = Join-Path $root '.venv\Scripts\python.exe'
$logs = Join-Path $root 'local_runtime\logs'

if (-not (Test-Path -LiteralPath (Join-Path $pgBin 'postgres.exe'))) { throw 'Portable PostgreSQL is missing under local_runtime\pgsql.' }
if (-not (Test-Path -LiteralPath (Join-Path $pgData 'PG_VERSION'))) { throw 'PostgreSQL data cluster is missing under local_runtime\pgdata.' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Python environment is missing under .venv.' }
if (-not (Test-Path -LiteralPath (Join-Path $root '.env'))) { throw 'Private .env is missing.' }
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# A stale loopback proxy (commonly 127.0.0.1:9 in restricted shells) makes
# urllib report every public data API as unreachable. Ignore only that invalid
# local proxy for this app's child process; preserve the caller's environment.
function Invoke-WithUnreachableLocalProxyDisabled {
    param([scriptblock]$Action)

    $removedProxies = @{}
    foreach ($name in @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if (-not $value) { continue }
        $proxyUri = $null
        if ([Uri]::TryCreate($value, [UriKind]::Absolute, [ref]$proxyUri) -and
            $proxyUri.IsLoopback -and $proxyUri.Port -eq 9) {
            $removedProxies[$name] = $value
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        }
    }

    try {
        & $Action | Out-Host
        return $LASTEXITCODE
    } finally {
        foreach ($name in $removedProxies.Keys) {
            [Environment]::SetEnvironmentVariable($name, $removedProxies[$name], 'Process')
        }
    }
}

$pgReady = & (Join-Path $pgBin 'pg_isready.exe') -h 127.0.0.1 -p 5432 2>$null
if ($LASTEXITCODE -ne 0) {
    $pgArgs = '-D "' + $pgData + '" -h 127.0.0.1 -p 5432'
    Start-Process -FilePath (Join-Path $pgBin 'postgres.exe') -ArgumentList $pgArgs -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'postgres.out.log') -RedirectStandardError (Join-Path $logs 'postgres.err.log') | Out-Null
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        & (Join-Path $pgBin 'pg_isready.exe') -h 127.0.0.1 -p 5432 *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    }
    if (-not $ready) { throw 'PostgreSQL did not start. See local_runtime\logs\postgres.err.log.' }
}

# Migrations are idempotent and must run before the API so new topology/reference tables
# are available after updating the repository.
$pythonExitCode = Invoke-WithUnreachableLocalProxyDisabled { & $python -m db.migrate }
if ($pythonExitCode -ne 0) { throw 'Database migrations failed.' }

# DPM waterways add local river/canal names and geometry.  They are reference-only and
# are imported once.  Network failure must not prevent the app from starting.
$pythonExitCode = Invoke-WithUnreachableLocalProxyDisabled { & $python -m scripts.ensure_dpm_hydrology }
if ($pythonExitCode -ne 0) {
    Write-Warning 'DPM hydrology reference import is not available yet; HydroRIVERS topology will still work.'
}

try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8899/health' -TimeoutSec 3
    if ($health.service -ne 'thailand-flood-intelligence') { throw 'Port 8899 belongs to another service.' }
} catch {
    if ($_.Exception.Message -match 'belongs to another service') { throw }
    $appArgs = '-m uvicorn app.main:app --host 127.0.0.1 --port 8899'
    Invoke-WithUnreachableLocalProxyDisabled {
        Start-Process -FilePath $python -ArgumentList $appArgs -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'app.out.log') -RedirectStandardError (Join-Path $logs 'app.err.log') | Out-Null
    } | Out-Null
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8899/health' -TimeoutSec 2
            if ($health.service -eq 'thailand-flood-intelligence') { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { throw 'App did not start. See local_runtime\logs\app.err.log.' }
}

Write-Output 'Thailand Flood Intelligence is ready at http://127.0.0.1:8899/'
Write-Output ('Database: ' + $health.database.state)
if ($OpenBrowser) { Start-Process 'http://127.0.0.1:8899/' }
