export type ProductAvailabilityLike = {
  sales_status?: string | null;
  stock_status?: string | null;
  available_quantity?: number | null;
  in_stock?: boolean | null;
};

export const isProductSoldOut = (product?: ProductAvailabilityLike | null) => {
  if (!product) return false;
  if (product.stock_status === "SOLD_OUT" || product.sales_status === "SOLD_OUT") return true;
  if (product.available_quantity !== null && product.available_quantity !== undefined) {
    return product.available_quantity <= 0;
  }
  return product.sales_status === "ON_SALE" && product.in_stock === false;
};
