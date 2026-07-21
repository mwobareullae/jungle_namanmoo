import { fetchWithTimeout, parseJson } from "../../../lib/api";
import { ADMIN_API_BASE } from "./adminApi";
import type { AdminOrderSummary } from "./adminOrderApi";
import type { IngredientMappingSummary } from "./adminIngredientMappingApi";

export type AdminDashboardProductStats = {
  totalCount: number;
  recommendableCount: number;
  imageMissingCount: number;
};

export type AdminDashboardStockStatusBreakdown = {
  inStockCount: number;
  lowStockCount: number;
  soldOutCount: number;
  hiddenCount: number;
  unknownCount: number;
};

export type AdminDashboardClaimSummary = {
  pendingCount: number;
};

export type AdminDashboardSummary = {
  orderSummary: AdminOrderSummary;
  ingredientReviewSummary: IngredientMappingSummary;
  productStats: AdminDashboardProductStats;
  stockStatusBreakdown: AdminDashboardStockStatusBreakdown;
  claimSummary: AdminDashboardClaimSummary;
};

type BackendAdminDashboardSummary = {
  order_summary: {
    pending_payment_count: number;
    preparing_shipment_count: number;
    shipped_count: number;
    cancel_requested_count: number;
    reserved_quantity_total: number;
  };
  ingredient_review_summary: {
    pending_count: number;
    held_count: number;
    needs_review_count: number;
    unclassified_count: number;
    approved_count: number;
    rejected_count: number;
  };
  product_stats: {
    total_count: number;
    recommendable_count: number;
    image_missing_count: number;
  };
  stock_status_breakdown: {
    in_stock_count: number;
    low_stock_count: number;
    sold_out_count: number;
    hidden_count: number;
    unknown_count: number;
  };
  claim_summary: {
    pending_count: number;
  };
};

export const getAdminDashboardSummary = async (): Promise<AdminDashboardSummary> => {
  const response = await fetchWithTimeout(`${ADMIN_API_BASE}/dashboard/summary`);
  const body = await parseJson<BackendAdminDashboardSummary>(response);
  return {
    orderSummary: {
      pendingPaymentCount: body.order_summary.pending_payment_count,
      preparingShipmentCount: body.order_summary.preparing_shipment_count,
      shippedCount: body.order_summary.shipped_count,
      cancelRequestedCount: body.order_summary.cancel_requested_count,
      reservedQuantityTotal: body.order_summary.reserved_quantity_total
    },
    ingredientReviewSummary: {
      pendingCount: body.ingredient_review_summary.pending_count,
      heldCount: body.ingredient_review_summary.held_count,
      needsReviewCount: body.ingredient_review_summary.needs_review_count,
      unclassifiedCount: body.ingredient_review_summary.unclassified_count,
      approvedCount: body.ingredient_review_summary.approved_count,
      rejectedCount: body.ingredient_review_summary.rejected_count
    },
    productStats: {
      totalCount: body.product_stats.total_count,
      recommendableCount: body.product_stats.recommendable_count,
      imageMissingCount: body.product_stats.image_missing_count
    },
    stockStatusBreakdown: {
      inStockCount: body.stock_status_breakdown.in_stock_count,
      lowStockCount: body.stock_status_breakdown.low_stock_count,
      soldOutCount: body.stock_status_breakdown.sold_out_count,
      hiddenCount: body.stock_status_breakdown.hidden_count,
      unknownCount: body.stock_status_breakdown.unknown_count
    },
    claimSummary: {
      pendingCount: body.claim_summary.pending_count
    }
  };
};
