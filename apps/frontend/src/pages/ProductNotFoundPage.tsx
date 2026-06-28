import EmptyState from "../components/EmptyState";

type ProductNotFoundPageProps = {
  onBack: () => void;
};

function ProductNotFoundPage({ onBack }: ProductNotFoundPageProps) {
  return (
    <div className="wrap detail-page">
      <EmptyState
        title="상품을 찾을 수 없어요"
        description="잘못된 product_id이거나 아직 mock 데이터에 없는 상품입니다."
        actionLabel="결과로 돌아가기"
        onAction={onBack}
      />
    </div>
  );
}

export default ProductNotFoundPage;
