import type { ProductDetailStatusProps } from "./types";

function ProductDetailStatus({ errorMessage, isLoading }: ProductDetailStatusProps) {
  if (isLoading) {
    return <div className="product-detail-loading-overlay" role="status" aria-label="상품 상세 불러오는 중"><span className="product-detail-loading-spinner" aria-hidden="true" /></div>;
  }

  if (errorMessage) {
    return <div className="detail-loading">{errorMessage}</div>;
  }

  return null;
}

export default ProductDetailStatus;
