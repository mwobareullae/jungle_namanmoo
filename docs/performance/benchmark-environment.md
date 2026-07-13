# Recommendation Benchmark Environment

이 문서는 추천 검색 성능을 측정하기 직전까지의 서버 환경 준비 방법을 정의한다. 이 작업은 추천 scoring이나 검색 성능을 개선하지 않으며, 실제 부하 테스트는 별도로 실행한다.

## 구조

- Linux 서버: 데이터셋 준비, DB/Elasticsearch 전환, backend 로그 보관
- Windows 로컬: k6로 서버 API 호출, 결과 다운로드 및 분석
- 서버에는 GitHub나 GitHub CLI가 필요하지 않다.

## 데이터셋 생성

전체 원본 데이터가 서버의 `/home/ubuntu/mwobareullae/data`에 있다면 서버에서 실행한다.

```bash
cd /home/ubuntu/mwobareullae
./scripts/perf/benchmarkctl build /home/ubuntu/mwobareullae/data
```

생성 결과는 다음 위치에 둔다.

```text
data/generated-subsets/benchmark-1000/
data/generated-subsets/benchmark-5000/
data/generated-subsets/benchmark-10000/
data/generated-subsets/benchmark-80000/
```

상품 ID를 오름차순으로 고정 선택하며, 상품 가격·성분·임베딩·리뷰 등 상품 관련 행은 같은 product_id를 기준으로 추출한다. 기존 `data/` 원본은 삭제하지 않는다.

## 서버 로컬 설정

서버에서만 `scripts/perf/config.env`를 만든다. 이 파일은 Git에 커밋하지 않는다.

```bash
cp scripts/perf/config.example.env scripts/perf/config.env
```

benchmark DB URL은 일반 dev DB가 아닌 benchmark 전용 DB를 사용한다.

```bash
BENCHMARK_DATABASE_URL='postgresql+psycopg://user:password@host:5432/mubarelle_bench_1000'
BENCHMARK_ACTIVATE=false
BENCHMARK_RESULT_ROOT='/opt/mwobareullae/benchmark-runs'
BENCHMARK_LOG_TAIL=5000
```

`BENCHMARK_DATABASE_URL`은 dataset을 바꿀 때 해당 benchmark DB로 변경한다. 운영 DB나 일반 dev DB를 지정하지 않는다.

## 데이터셋 준비와 검증

```bash
./scripts/perf/benchmarkctl prepare 1000
./scripts/perf/benchmarkctl verify 1000
```

다른 데이터셋:

```bash
./scripts/perf/benchmarkctl prepare 5000
./scripts/perf/benchmarkctl prepare 10000
./scripts/perf/benchmarkctl prepare 80000
```

`prepare`는 migration, seed, Elasticsearch 색인, 상품 수 검증을 실행한다. benchmark DB URL과 데이터 디렉터리가 명시되지 않으면 중단한다.

## backend 활성화

prepare만 실행하면 현재 backend는 재시작되지 않는다. 검증이 끝난 뒤 benchmark DB를 API에 연결한다.

```bash
./scripts/perf/benchmarkctl activate 1000
```

이 명령은 `docker-compose.benchmark.yml`을 사용해 backend만 재생성한다. 일반 dev DB와 Elasticsearch 색인은 변경하지 않는다. 자동 활성화가 필요하면 서버의 `config.env`에 `BENCHMARK_ACTIVATE=true`를 둔다.

## 결과 수집

부하 테스트가 끝난 뒤 서버에서 실행한다.

```bash
./scripts/perf/benchmarkctl collect 20260713-153000-recommendation-1000-1vu 1000
```

결과는 `BENCHMARK_RESULT_ROOT/<run_id>/`에 저장된다.

```text
manifest.json
context.txt
backend/backend.log
database/slow-query.log
elasticsearch/node-stats.json
resources/docker-stats.csv
resources/compose-ps.txt
k6/
summary/
```

## Windows에서 결과 가져오기

```powershell
scp -r ubuntu@SERVER:/opt/mwobareullae/benchmark-runs/RUN_ID C:\github\weapon\junlge_namanmoo\perf-runs\
```

원본 로그는 Git에 넣지 않고, 분석 후 요약과 그래프만 `docs/performance/records/`에 저장한다.
