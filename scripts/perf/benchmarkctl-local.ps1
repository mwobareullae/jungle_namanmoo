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
        if ($line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { continue }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
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
    Write-Host "[1/6] 서버 benchmark subset 생성 및 준비"
    $prepareCommand = 'cd ' + $RemoteAppDir + ' && ' + $RemoteCtl + ' build ' + $RemoteAppDir + '/data && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' ' + $RemoteCtl + ' prepare ' + $Dataset
    Invoke-Ssh $prepareCommand $Config
} else {
    Write-Host "[1/6] 서버 benchmark 상태 검증"
    $verifyCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' ' + $RemoteCtl + ' verify ' + $Dataset
    Invoke-Ssh $verifyCommand $Config
}

Write-Host "[2/6] benchmark backend 활성화"
$activateCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' ' + $RemoteCtl + ' activate ' + $Dataset
Invoke-Ssh $activateCommand $Config

$effectiveVus = if ($Vus -gt 0) { $Vus } elseif ($Config.ContainsKey("VUS") -and $Config.VUS) { $Config.VUS } else { "1" }
$effectiveDuration = if ($Duration) { $Duration } elseif ($Config.ContainsKey("DURATION") -and $Config.DURATION) { $Config.DURATION } else { "30s" }
$sla = if ($Config.ContainsKey("SLA_MS") -and $Config.SLA_MS) { $Config.SLA_MS } else { "3000" }

Write-Host "[3/6] 로컬 k6 실행: dataset=$Dataset user_type=$UserType"
$k6Args = @(
    "run", $K6Script,
    "-e", "BASE_URL=$BaseUrl",
    "-e", "DATASET=$Dataset",
    "-e", "USER_TYPE=$UserType",
    "-e", "VUS=$effectiveVus",
    "-e", "DURATION=$effectiveDuration",
    "-e", "SLA_MS=$sla",
    "--summary-export", $LocalK6Summary
)
foreach ($name in @(
    "BENCHMARK_PROFILE_USER_EMAIL", "BENCHMARK_PROFILE_USER_PASSWORD",
    "BENCHMARK_SKIN_TEST_USER_EMAIL", "BENCHMARK_SKIN_TEST_USER_PASSWORD",
    "BENCHMARK_BEHAVIOR_USER_EMAIL", "BENCHMARK_BEHAVIOR_USER_PASSWORD",
    "AUTH_COOKIE", "SKIN_TYPE", "SENSITIVITY", "AVOID_INGREDIENTS"
)) {
    if ($Config.ContainsKey($name) -and $Config[$name]) {
        $k6Args += @("-e", "$name=$($Config[$name])")
    }
}
& k6 @k6Args
if ($LASTEXITCODE -ne 0) { throw "k6 실행 실패" }

Write-Host "[4/6] k6 결과를 서버로 업로드"
Invoke-Scp @(
    "-F", "NUL", "-i", $SshKey,
    $LocalK6Summary,
    "${Remote}:$RemoteK6Summary"
)

Write-Host "[5/6] 서버에서 결과 collect"
$collectCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' BENCHMARK_K6_RESULT_FILE=' + $RemoteK6Summary + ' ' + $RemoteCtl + ' collect ' + $RunId + ' ' + $Dataset
Invoke-Ssh $collectCommand $Config

Write-Host "[6/6] 수집 결과 다운로드"
Invoke-Scp @(
    "-F", "NUL", "-i", $SshKey, "-r",
    "${Remote}:$RemoteRuntimeRoot/runs/$RunId",
    $LocalResultRoot
)

Write-Host "완료: $LocalResultRoot\$RunId"
