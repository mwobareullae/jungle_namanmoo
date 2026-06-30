# Frontend

Vite, React, TypeScript 기반 프론트엔드입니다.

## 예정 화면

- S1 고민 입력
- S2 분석 로딩
- S3 추천 결과
- S4 상품 상세

## 현재 상태

`http://localhost:5173`에서 FastAPI 백엔드와 연결된 S1~S4 플로우를 확인할 수 있습니다.

## API 설정

프론트는 `VITE_API_BASE_URL`의 실제 백엔드 API를 호출하고, `VITE_APP_MODE`로 커머스/커뮤니티 노출 범위를 나눕니다.

```env
VITE_APP_MODE=commerce
VITE_API_BASE_URL=http://localhost:8000/api
VITE_GA_MEASUREMENT_ID=
```

커뮤니티 프리뷰 배포 예시:

```env
VITE_APP_MODE=community
VITE_API_BASE_URL=https://api.mubarelle.com/api
VITE_GA_MEASUREMENT_ID=G-XXXXXXXXXX
```

변경 후에는 프론트 dev server 또는 Docker Compose frontend 서비스를 다시 시작합니다.

## 개발 명령

```bash
npm install
npm run dev
npm run typecheck
npm run lint
npm run format
npm run build
```
