import type { ProductDetailStatusProps } from "./types";

function ProductDetailStatus({ errorMessage, isLoading }: ProductDetailStatusProps) {
  if (isLoading) {
    return <div className="detail-loading">상품 상세 정보를 불러오는 중입니다.</div>;
  }

  if (errorMessage) {
    return <div className="detail-loading">{errorMessage}</div>;
  }

  return null;
}

export default ProductDetailStatus;
