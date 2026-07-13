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

The same command can be repeated with `DATASET=5000`, `DATASET=10000`, and `DATASET=80000`. Change only the dataset and the server-side benchmark profile between runs.

## Collect on server

```bash
./scripts/perf/benchmarkctl collect 20260713-153000-recommendation-1000-1vu 1000
```

The server stores raw logs under `BENCHMARK_RESULT_ROOT/<run_id>`. Download that directory with `scp` and keep only redacted summaries and charts in Git.
