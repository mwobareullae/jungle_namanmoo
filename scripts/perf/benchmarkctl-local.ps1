[CmdletBinding()]
param(
    [ValidateSet("1000", "5000", "10000", "80000")]
    [string]$Dataset = "1000",
    [ValidateSet("anonymous", "profile", "skin-test", "behavior", "full-personalized")]
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

function Set-RemoteBenchmarkDatabase([string]$Dataset, [string]$RemoteConfig, [hashtable]$Config) {
    $databaseName = "mubarelle_bench_$Dataset"
    $remoteScript = @(
        'set -euo pipefail',
        "config='$RemoteConfig'",
        "database='$databaseName'",
        'line=$(grep -E ''^BENCHMARK_DATABASE_URL='' "$config" | tail -n 1 || true)',
        'if [ -z "$line" ]; then echo "BENCHMARK_DATABASE_URL missing in $config" >&2; exit 1; fi',
        'url=$(printf ''%s\n'' "${line#BENCHMARK_DATABASE_URL=}" | tr -d ''"'')',
        'base="${url%/*}"',
        'new_url="${base}/${database}"',
        'tmp="${config}.tmp.$$"',
        'awk -v new_url="$new_url" ''BEGIN { replaced=0 } /^BENCHMARK_DATABASE_URL=/ { print "BENCHMARK_DATABASE_URL=" new_url; replaced=1; next } { print } END { if (!replaced) exit 42 }'' "$config" > "$tmp"',
        'mv "$tmp" "$config"',
        'echo "benchmark database set: ${database}"'
    ) -join "`n"
    $encodedScript = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($remoteScript))
    $remoteCommand = "printf %s $encodedScript | base64 -d | bash"
    Invoke-Ssh $remoteCommand $Config
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
$ServerHost = ([System.Uri]$BaseUrl).Host
$SshUser = Require-Config $Config "SSH_USER"
$SshHost = Require-Config $Config "SSH_HOST"
$SshKey = Require-Config $Config "SSH_KEY"
$Remote = "$SshUser@$SshHost"
$RunId = "recommendation-$Dataset-$UserType-$(Get-Date -Format yyyyMMdd-HHmmss)"
$LocalRunDir = Join-Path $LocalResultRoot $RunId
$LocalK6Summary = Join-Path $LocalRunDir "k6-summary.json"
$LocalK6Output = Join-Path $LocalRunDir "k6-output.txt"
$RemoteK6Summary = "/tmp/$RunId-k6-summary.json"
$RemoteK6Output = "/tmp/$RunId-k6-output.txt"
$RemoteConfig = "$RemoteRuntimeRoot/config.benchmark.env"
$RemoteCtl = "$RemoteAppDir/scripts/perf/benchmarkctl"

New-Item -ItemType Directory -Force $LocalRunDir | Out-Null

if ($Prepare) {
    Write-Host "[1/11] 서버 benchmark subset 생성"
    $buildCommand = 'cd ' + $RemoteAppDir + ' && ' + $RemoteCtl + ' build ' + $RemoteAppDir + '/data'
    Invoke-Ssh $buildCommand $Config
} else {
    Write-Host "[1/11] 서버 benchmark subset 생성 생략"
}

Write-Host "[2/11] benchmark DB 대상 설정"
Set-RemoteBenchmarkDatabase $Dataset $RemoteConfig $Config

Write-Host "[3/11] benchmark backend 활성화"
$activateCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' ' + $RemoteCtl + ' activate ' + $Dataset
Invoke-Ssh $activateCommand $Config
$HealthUrl = $BaseUrl.TrimEnd("/") + "/health"
Wait-HttpReady $HealthUrl

if ($Prepare) {
    Write-Host "[4/11] 서버 benchmark DB 준비"
    $prepareCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' ' + $RemoteCtl + ' prepare ' + $Dataset
    Invoke-Ssh $prepareCommand $Config
} else {
    Write-Host "[4/11] 서버 benchmark 상태 검증"
    $verifyUserOverride = if ($UserType -eq "full-personalized") { ' BENCHMARK_VERIFY_USERS=false' } else { '' }
    $verifyCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + $verifyUserOverride + ' ' + $RemoteCtl + ' verify ' + $Dataset
    Invoke-Ssh $verifyCommand $Config
}

if ($UserType -eq "full-personalized") {
    Write-Host "[5/11] full-personalized fixture 준비"
    $seedUsersCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' ' + $RemoteCtl + ' seed-users ' + $Dataset
    Invoke-Ssh $seedUsersCommand $Config
} else {
    Write-Host "[5/11] full-personalized fixture 준비 생략"
}

$effectiveVus = if ($Vus -gt 0) { $Vus } elseif ($Config.ContainsKey("VUS") -and $Config.VUS) { $Config.VUS } else { "1" }
$effectiveDuration = if ($Duration) { $Duration } elseif ($Config.ContainsKey("DURATION") -and $Config.DURATION) { $Config.DURATION } else { "30s" }
$sla = if ($Config.ContainsKey("SLA_MS") -and $Config.SLA_MS) { $Config.SLA_MS } else { "3000" }

$RunStartedAt = (Get-Date).ToUniversalTime().ToString("o")
Write-Host "[6/11] 서버 resource monitor 시작"
$monitorStartCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' BENCHMARK_RUN_STARTED_AT=' + $RunStartedAt + ' ' + $RemoteCtl + ' monitor-start ' + $RunId + ' ' + $Dataset
Invoke-Ssh $monitorStartCommand $Config

Write-Host "[7/11] 로컬 k6 실행: dataset=$Dataset user_type=$UserType"
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
    "BENCHMARK_FULL_PERSONALIZED_USER_EMAILS", "BENCHMARK_FULL_PERSONALIZED_USER_PASSWORD",
    "BENCHMARK_FULL_PERSONALIZED_USER_COUNT",
    "BENCHMARK_FULL_PERSONALIZED_USER_EMAIL_PREFIX", "BENCHMARK_FULL_PERSONALIZED_USER_EMAIL_DOMAIN",
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
$k6ExitCode = 0
$RunFinishedAt = $null
try {
    & k6 @k6Args 2>&1 | Tee-Object -FilePath $LocalK6Output
    $k6ExitCode = $LASTEXITCODE
} finally {
    $RunFinishedAt = (Get-Date).ToUniversalTime().ToString("o")
    Write-Host "[8/11] 서버 resource monitor 종료"
    $monitorStopCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' BENCHMARK_RUN_FINISHED_AT=' + $RunFinishedAt + ' ' + $RemoteCtl + ' monitor-stop ' + $RunId + ' ' + $Dataset
    try {
        Invoke-Ssh $monitorStopCommand $Config
    } catch {
        Write-Warning "resource monitor stop failed: $_"
    }
}
if (-not (Test-Path -LiteralPath $LocalK6Summary)) {
    throw "k6 summary file was not created: $LocalK6Summary"
}
if ($k6ExitCode -ne 0) {
    Write-Warning "k6 exited with code $k6ExitCode; collecting benchmark artifacts before failing."
}

Write-Host "[9/11] k6 결과를 서버로 업로드"
Invoke-Scp @(
    "-F", "NUL", "-i", $SshKey,
    $LocalK6Summary,
    "${Remote}:$RemoteK6Summary"
)
if (Test-Path -LiteralPath $LocalK6Output) {
    Invoke-Scp @(
        "-F", "NUL", "-i", $SshKey,
        $LocalK6Output,
        "${Remote}:$RemoteK6Output"
    )
}

Write-Host "[10/11] 서버에서 결과 collect"
$collectCommand = 'cd ' + $RemoteAppDir + ' && BENCHMARK_CONFIG_FILE=' + $RemoteConfig + ' BENCHMARK_K6_RESULT_FILE=' + $RemoteK6Summary + ' BENCHMARK_K6_OUTPUT_FILE=' + $RemoteK6Output + ' BENCHMARK_USER_TYPE=' + $UserType + ' BENCHMARK_VUS=' + $effectiveVus + ' BENCHMARK_DURATION=' + $effectiveDuration + ' BENCHMARK_SERVER_HOST=' + $ServerHost + ' BENCHMARK_RUN_STARTED_AT=' + $RunStartedAt + ' BENCHMARK_RUN_FINISHED_AT=' + $RunFinishedAt + ' BENCHMARK_K6_EXIT_CODE=' + $k6ExitCode + ' ' + $RemoteCtl + ' collect ' + $RunId + ' ' + $Dataset
Invoke-Ssh $collectCommand $Config

Write-Host "[11/11] 수집 결과 다운로드"
Invoke-Scp @(
    "-F", "NUL", "-i", $SshKey, "-r",
    "${Remote}:$RemoteRuntimeRoot/runs/$RunId",
    $LocalResultRoot
)

Write-Host "완료: $LocalResultRoot\$RunId"
if ($k6ExitCode -ne 0) {
    throw "k6 실행 실패: exit_code=$k6ExitCode"
}
