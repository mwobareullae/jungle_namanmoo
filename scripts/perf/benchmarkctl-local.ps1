[CmdletBinding()]
param(
    [ValidateSet("1000", "5000", "10000", "80000")]
    [string]$Dataset = "1000",
    [ValidateSet("anonymous", "profile", "skin-test", "behavior")]
    [string]$UserType = "anonymous",
    [switch]$Prepare,
    [int]$Vus,
    [string]$Duration
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$ConfigPath = Join-Path $PSScriptRoot "config.benchmark.local.env"
$K6Script = Join-Path $RepoRoot "tests/k6/recommendation-benchmark.js"
$LocalResultRoot = Join-Path $RepoRoot "perf-runs"

function Read-EnvFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "설정 파일이 없습니다: $Path"
    }

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*#' -or $line -match '^\s*$') { continue }
        $match = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$')
        if (-not $match.Success) {
            continue
        }
        $name = $match.Groups[1].Value
        $value = $match.Groups[2].Value.Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$name] = $value
    }
    return $values
}

function Require-Config([hashtable]$Config, [string]$Name) {
    if (-not $Config.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace($Config[$Name])) {
        throw "로컬 benchmark 설정이 없습니다: $Name ($ConfigPath)"
    }
    return [string]$Config[$Name]
}

function Invoke-Ssh([string]$Command, [hashtable]$Config) {
    $sshArgs = @(
        "-F", "NUL",
        "-o", "BatchMode=yes",
        "-i", (Require-Config $Config "SSH_KEY"),
        "$(Require-Config $Config 'SSH_USER')@$(Require-Config $Config 'SSH_HOST')",
        $Command
    )
    & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) { throw "SSH 명령 실패: $Command" }
}

function Invoke-Scp([string[]]$Arguments) {
    & scp @Arguments
    if ($LASTEXITCODE -ne 0) { throw "SCP 명령 실패" }
}

function Wait-HttpReady([string]$Url, [int]$TimeoutSeconds = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $status = & curl.exe -s -o NUL -w "%{http_code}" --max-time 2 $Url
            if ($status -eq "200") {
                Write-Host "backend health ready: $Url"
                return
            }
        } catch {
            # Retry until the backend finishes restarting.
        }
        Start-Sleep -Seconds 2
    }
    throw "backend health check timed out: $Url"
}

$Config = Read-EnvFile $ConfigPath
$RemoteAppDir = Require-Config $Config "REMOTE_APP_DIR"
$RemoteRuntimeRoot = Require-Config $Config "REMOTE_BENCHMARK_ROOT"
$BaseUrl = Require-Config $Config "BASE_URL"
$SshUser = Require-Config $Config "SSH_USER"
$SshHost = Require-Config $Config "SSH_HOST"
$SshKey = Require-Config $Config "SSH_KEY"
$Remote = "$SshUser@$SshHost"
$RunId = "recommendation-$Dataset-$UserType-$(Get-Date -Format yyyyMMdd-HHmmss)"
$LocalRunDir = Join-Path $LocalResultRoot $RunId
$LocalK6Summary = Join-Path $LocalRunDir "k6-summary.json"
$RemoteK6Summary = "/tmp/$RunId-k6-summary.json"
$RemoteConfig = "$RemoteRuntimeRoot/config.benchmark.env"
$RemoteCtl = "$RemoteAppDir/scripts/perf/benchmarkctl"

New-Item -ItemType Directory -Force $LocalRunDir | Out-Null

if ($Prepare) {
    Write-Host "[1/7] 서버 benchmark subset 생성"
    $buildCommand = 'cd ' + $RemoteAppDir + ' && ' + $RemoteCtl + ' build ' + $RemoteAppDir + '/data'
    Invoke-Ssh $buildCommand $Config
} else {
    Write-Host "[1/7] 서버 benchmark subset 생성 생략"
}

Write-Host "[2/7] benchmark backend 활성화"
$activateCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' ' + $RemoteCtl + ' activate ' + $Dataset
Invoke-Ssh $activateCommand $Config
$HealthUrl = $BaseUrl.TrimEnd("/") + "/health"
Wait-HttpReady $HealthUrl

if ($Prepare) {
    Write-Host "[3/7] 서버 benchmark DB 준비"
    $prepareCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' ' + $RemoteCtl + ' prepare ' + $Dataset
    Invoke-Ssh $prepareCommand $Config
} else {
    Write-Host "[3/7] 서버 benchmark 상태 검증"
    $verifyCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' ' + $RemoteCtl + ' verify ' + $Dataset
    Invoke-Ssh $verifyCommand $Config
}

$effectiveVus = if ($Vus -gt 0) { $Vus } elseif ($Config.ContainsKey("VUS") -and $Config.VUS) { $Config.VUS } else { "1" }
$effectiveDuration = if ($Duration) { $Duration } elseif ($Config.ContainsKey("DURATION") -and $Config.DURATION) { $Config.DURATION } else { "30s" }
$sla = if ($Config.ContainsKey("SLA_MS") -and $Config.SLA_MS) { $Config.SLA_MS } else { "3000" }

Write-Host "[4/7] 로컬 k6 실행: dataset=$Dataset user_type=$UserType"
$k6Args = @(
    "run",
    "--summary-export", $LocalK6Summary,
    "-e", "BASE_URL=$BaseUrl",
    "-e", "DATASET=$Dataset",
    "-e", "USER_TYPE=$UserType",
    "-e", "VUS=$effectiveVus",
    "-e", "DURATION=$effectiveDuration",
    "-e", "SLA_MS=$sla"
)
foreach ($envName in @(
    "BENCHMARK_PROFILE_USER_EMAIL", "BENCHMARK_PROFILE_USER_PASSWORD",
    "BENCHMARK_SKIN_TEST_USER_EMAIL", "BENCHMARK_SKIN_TEST_USER_PASSWORD",
    "BENCHMARK_BEHAVIOR_USER_EMAIL", "BENCHMARK_BEHAVIOR_USER_PASSWORD",
    "AUTH_COOKIE", "SKIN_TYPE", "SENSITIVITY", "AVOID_INGREDIENTS"
)) {
    if ($Config.ContainsKey($envName)) {
        $envValue = [string]$Config.Item($envName)
        if (-not [string]::IsNullOrWhiteSpace($envValue)) {
            $k6Args += @("-e", "${envName}=${envValue}")
        }
    }
}
$k6Args += $K6Script
& k6 @k6Args
$k6ExitCode = $LASTEXITCODE
if (-not (Test-Path -LiteralPath $LocalK6Summary)) {
    throw "k6 summary file was not created: $LocalK6Summary"
}
if ($k6ExitCode -ne 0) {
    Write-Warning "k6 exited with code $k6ExitCode; collecting benchmark artifacts before failing."
}

Write-Host "[5/7] k6 결과를 서버로 업로드"
Invoke-Scp @(
    "-F", "NUL", "-i", $SshKey,
    $LocalK6Summary,
    "${Remote}:$RemoteK6Summary"
)

Write-Host "[6/7] 서버에서 결과 collect"
$collectCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' BENCHMARK_K6_RESULT_FILE=' + $RemoteK6Summary + ' ' + $RemoteCtl + ' collect ' + $RunId + ' ' + $Dataset
Invoke-Ssh $collectCommand $Config

Write-Host "[7/7] 수집 결과 다운로드"
Invoke-Scp @(
    "-F", "NUL", "-i", $SshKey, "-r",
    "${Remote}:$RemoteRuntimeRoot/runs/$RunId",
    $LocalResultRoot
)

Write-Host "완료: $LocalResultRoot\$RunId"
if ($k6ExitCode -ne 0) {
    throw "k6 실행 실패: exit_code=$k6ExitCode"
}
