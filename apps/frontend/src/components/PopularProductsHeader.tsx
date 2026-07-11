type Category = { code: string; label: string; icon?: string };

const categories: Category[] = [
  { code: "", label: "전체" },
  { code: "toner", label: "토너", icon: "/category-icons/toner.png" },
  { code: "serum", label: "세럼", icon: "/category-icons/serum.png" },
  { code: "cream", label: "크림", icon: "/category-icons/cream.png" },
  { code: "sunscreen", label: "선크림", icon: "/category-icons/sunscreen.png" }
];

const getCurrentMonthWeekLabel = () => {
  const today = new Date();
  return `${today.getMonth() + 1}월 ${Math.ceil(today.getDate() / 7)}주차`;
};

const getCurrentDateLabel = () => {
  const today = new Date();
  return `${today.getFullYear()}.${String(today.getMonth() + 1).padStart(2, "0")}.${String(today.getDate()).padStart(2, "0")}.`;
};

const getWindowLabel = (windowDays: number) => {
  if (windowDays === 1) return "오늘";
  if (windowDays === 30) return "최근 30일간";
  return "최근 7일간";
};

type PopularProductsHeaderProps = {
  category: string;
  windowDays: number;
  onCategoryChange?: (category: string) => void;
  onWindowDaysChange?: (windowDays: number) => void;
};

function PopularProductsHeader({
  category,
  windowDays,
  onCategoryChange,
  onWindowDaysChange
}: PopularProductsHeaderProps) {
  return (
    <>
      <div className="popular-products-kicker">{getCurrentMonthWeekLabel()}</div>
      <h1>많이 본 BEST</h1>
      <div className="popular-category-tabs" role="tablist" aria-label="상품 카테고리">
        {categories.map((item) => (
          <button
            className={category === item.code ? "is-active" : ""}
            key={item.code || "all"}
            onClick={() => onCategoryChange?.(item.code)}
            role="tab"
            type="button"
          >
            <span className="popular-category-icon">
              {item.icon ? (
                <img alt="" onError={(event) => { event.currentTarget.style.display = "none"; }} src={item.icon} />
              ) : item.code ? "✦" : "ALL"}
            </span>
            <span>{item.label}</span>
          </button>
        ))}
      </div>
      <div className="popular-products-toolbar">
        <div className="popular-period-tabs" role="tablist" aria-label="인기 기간">
          <button className={windowDays === 1 ? "is-active" : ""} onClick={() => onWindowDaysChange?.(1)} type="button">일간</button>
          <button className={windowDays === 7 ? "is-active" : ""} onClick={() => onWindowDaysChange?.(7)} type="button">주간</button>
          <button className={windowDays === 30 ? "is-active" : ""} onClick={() => onWindowDaysChange?.(30)} type="button">월간</button>
        </div>
        <span className="popular-ranking-info">
          <span>인기 기준</span>
          <button aria-label="인기상품 순위 기준 안내" className="popular-ranking-info__trigger" type="button">
            <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="9.5" />
              <path d="M12 10.5v5" />
              <circle cx="12" cy="7.2" r="0.8" fill="currentColor" stroke="none" />
            </svg>
          </button>
          <span className="popular-ranking-info__tooltip" role="tooltip">
            {getCurrentDateLabel()} 기준, {getWindowLabel(windowDays)} 고객들의 다양한 상품 활동을 종합해 인기상품 순위를 제공하고 있습니다.
          </span>
        </span>
      </div>
    </>
  );
}

export default PopularProductsHeader;
