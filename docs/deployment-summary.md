# Deployment Summary

이 문서는 Phase 0 개발 서버 배포 방식을 고정하기 위한 결정 기록입니다.

## 현재 결정

Phase 0에서는 production 배포를 만들지 않고, `dev` 브랜치 전용 개발 서버만 운영합니다.

```text
dev branch push -> GitHub Actions -> EC2 dev server -> Docker Compose
main branch push -> no production deployment yet
```

## Dev 서버 구성

- AWS EC2 1대
- Ubuntu 24.04 LTS 권장
- Docker + Docker Compose
- `frontend`, `backend`, `postgres` 컨테이너를 같은 EC2에서 실행
- DB는 RDS가 아니라 EC2 내부 Postgres container로 시작
- OpenAI 관련 환경변수는 placeholder만 있으며 현재 Hello World 환경에서는 사용하지 않음

## 권장 EC2 사양

- Instance type: `t3.small`
- Storage: gp3 30GB

`t3.micro`도 가능하지만 frontend, backend, Postgres를 함께 빌드/실행하면 메모리 부족으로 시간이 낭비될 수 있습니다.

## 보안그룹 기준

초기 dev 확인 단계:

```text
22    SSH, 관리자 IP 또는 GitHub Actions 접근 방식에 맞게 제한
5173  frontend, 팀원 IP 또는 임시 공개
8000  backend, 팀원 IP 또는 임시 공개
5432  postgres, 외부 공개 금지
```

추후 Caddy/Nginx를 붙인 뒤:

```text
22    관리자 IP만 허용
80    전체 허용
443   전체 허용
5173  외부 차단
8000  외부 차단
5432  외부 차단
```

## GitHub Actions SSH 배포 주의

현재 `cd-dev.yml`은 GitHub-hosted runner가 EC2에 SSH 접속하는 방식입니다.

EC2에 repository를 미리 clone할 필요는 없습니다. GitHub Actions가 현재 checkout된 소스를 `rsync`로 `DEV_APP_DIR`에 동기화합니다.

서버의 `.env`는 GitHub Actions가 덮어쓰지 않습니다. 서버에 `.env`가 없으면 첫 배포 때 `.env.example`을 복사해 생성하고, 실제 dev secret은 EC2에서 직접 수정합니다.

따라서 EC2 보안그룹의 SSH 인바운드가 GitHub-hosted runner에서 접근 가능해야 합니다. 더 안전한 방식은 추후 아래 중 하나로 전환합니다.

- self-hosted runner를 EC2에 설치
- AWS credentials로 배포 직전에 GitHub Actions runner IP만 보안그룹에 임시 허용 후 제거
- Caddy/Nginx와 별도 배포 채널 정리

## 아직 하지 않는 것

- production 자동 배포
- RDS
- ECS/Fargate
- ALB
- ECR
- 도메인/HTTPS 자동화
- 자동 DB 백업

이 항목들은 발표 전 안정화 또는 운영 전환 단계에서 별도로 결정합니다.
