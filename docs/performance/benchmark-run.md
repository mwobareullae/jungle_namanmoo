# Recommendation Benchmark Run

환경 준비와 실제 부하 실행을 분리한다. `benchmarkctl`은 서버 Linux에서 실행하고 k6는 Windows 로컬에서 실행한다.

## Server

```bash
./scripts/perf/benchmarkctl prepare 1000
./scripts/perf/benchmarkctl verify 1000
./scripts/perf/benchmarkctl activate 1000
```

## Windows

```powershell
k6 run tests/k6/recommendation-benchmark.js `
  -e BASE_URL=https://dev.api.mubarelle.com/api `
  -e DATASET=1000 `
  -e USER_TYPE=anonymous `
  -e VUS=1 `
  -e DURATION=30s `
  -e SLA_MS=3000
```

Save the k6 summary locally and copy it to the Linux server before collecting
the server-side measurements.

```powershell
k6 run tests/k6/recommendation-benchmark.js `
  -e BASE_URL=https://dev.api.mubarelle.com/api `
  -e DATASET=1000 `
  -e USER_TYPE=anonymous `
  --summary-export .\perf-runs\recommendation-1000-k6-summary.json

scp .\perf-runs\recommendation-1000-k6-summary.json `
  ubuntu@SERVER:/tmp/recommendation-1000-k6-summary.json
```

The same command can be repeated with `DATASET=5000`, `DATASET=10000`, and `DATASET=80000`. Change only the dataset and the server-side benchmark profile between runs.

For an authenticated fixture, k6 logs in once during `setup()` and reuses the
returned session cookie for the recommendation requests. Supply the credentials
only through the local shell or an ignored environment file.

```powershell
$env:BENCHMARK_PROFILE_USER_EMAIL = "profile@example.test"
$env:BENCHMARK_PROFILE_USER_PASSWORD = "<local-only-password>"
k6 run tests/k6/recommendation-benchmark.js `
  -e BASE_URL=https://dev.api.mubarelle.com/api `
  -e DATASET=1000 `
  -e USER_TYPE=profile `
  -e BENCHMARK_PROFILE_USER_EMAIL=$env:BENCHMARK_PROFILE_USER_EMAIL `
  -e BENCHMARK_PROFILE_USER_PASSWORD=$env:BENCHMARK_PROFILE_USER_PASSWORD `
  -e VUS=1 `
  -e DURATION=30s `
  -e SLA_MS=3000
```

`skin-test` and `behavior` use the corresponding environment variable names in
`docs/performance/benchmark-users.json`. The accounts must already contain the
intended saved profile, latest skin-test result, or behavior history. The k6
script does not create or mutate fixture users.

## Collect on server

```bash
BENCHMARK_K6_RESULT_FILE=/tmp/recommendation-1000-k6-summary.json \
./scripts/perf/benchmarkctl collect 20260713-153000-recommendation-1000-1vu 1000
```

The server stores raw logs and the k6 summary under
`BENCHMARK_RESULT_ROOT/<run_id>`. Download that directory with `scp` and keep
only redacted summaries and charts in Git.
