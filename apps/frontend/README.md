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

### 커뮤니티 모드 노출 기준

`VITE_APP_MODE=community`에서는 커머스 행동을 막고 추천/성분 정보 중심으로 노출합니다.

- 숨김: 로그인, 찜, 장바구니, 구매하기, 구매처 탭/섹션, checkout/payment-complete 화면
- 유지: 검색, 추천 결과, 상품 상세, 가격 표시, 추천 점수, 성분 근거, AI 추천 요약
- 라우팅: `/checkout`, `/payment-complete` 접근 시 홈(`/`)으로 되돌립니다.
- 구현 기준: 커머스 전용 UI에는 `data-commerce-only`를 붙이고, `html[data-app-mode="community"]` CSS에서 숨깁니다.

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
