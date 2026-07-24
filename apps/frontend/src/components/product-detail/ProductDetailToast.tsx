import ActivityToast from "../ui/ActivityToast";
import type { ProductDetailToastProps } from "./types";

function ProductDetailToast({ message }: ProductDetailToastProps) {
  return <ActivityToast message={message} />;
}

export default ProductDetailToast;
