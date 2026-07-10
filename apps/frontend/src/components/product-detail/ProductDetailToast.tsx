import type { ProductDetailToastProps } from "./types";

function ProductDetailToast({ message }: ProductDetailToastProps) {
  if (!message) {
    return null;
  }

  return (
    <div className="activity-toast" role="status" aria-live="polite">
      <span className="activity-toast__dot" />
      {message}
    </div>
  );
}

export default ProductDetailToast;
