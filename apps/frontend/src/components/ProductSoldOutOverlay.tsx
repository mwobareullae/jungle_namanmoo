type ProductSoldOutOverlayProps = {
  label?: string;
};

function ProductSoldOutOverlay({ label = "일시품절" }: ProductSoldOutOverlayProps) {
  return <span className="product-sold-out-overlay" aria-label={label}>{label}</span>;
}

export default ProductSoldOutOverlay;
