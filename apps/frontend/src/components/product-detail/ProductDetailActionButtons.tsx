import type { ProductDetailActionButtonsProps } from "./types";

function ProductDetailActionButtons({
  displayedIsWished,
  isWishlistPending,
  onToggleWishlist,
}: ProductDetailActionButtonsProps) {
  return (
    <div className="detail-actions">
      <button className="detail-icon-btn" type="button" aria-label="공유">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="18" cy="5" r="3" />
          <circle cx="6" cy="12" r="3" />
          <circle cx="18" cy="19" r="3" />
          <path d="M8.59 13.51 15.42 17.49M15.41 6.51 8.59 10.49" />
        </svg>
      </button>
      <button
        aria-label={displayedIsWished ? "찜 해제" : "찜"}
        aria-pressed={displayedIsWished}
        className={`detail-icon-btn${displayedIsWished ? " is-wished" : ""}`}
        data-commerce-only
        disabled={isWishlistPending}
        onClick={onToggleWishlist}
        type="button"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill={displayedIsWished ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l7.78-8.84a5.5 5.5 0 0 0 1.06-7.78z" />
        </svg>
      </button>
    </div>
  );
}

export default ProductDetailActionButtons;
