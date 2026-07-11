import { Link } from "react-router-dom";
import { callOriginal } from "../lib/originalRuntime";

const categoryGroups = [
  {
    title: "스킨케어",
    items: [
      "스킨/토너",
      "에센스/세럼/앰플",
      "크림",
      "로션",
      "미스트/오일",
      "스킨케어 세트",
      "스킨케어 디바이스"
    ]
  },
  {
    title: "클렌징",
    items: [
      "클렌징폼/젤",
      "오일/밤",
      "워터/밀크",
      "필링&스크럽",
      "티슈/패드",
      "립&아이리무버",
      "클렌징 디바이스"
    ]
  },
  {
    title: "바디케어",
    items: [
      "샤워/입욕",
      "바디로션/크림",
      "오일/미스트",
      "제모/왁싱",
      "데오드란트",
      "핸드케어",
      "풋케어",
      "유아동/임산부"
    ]
  },
  {
    title: "헤어케어",
    items: [
      "샴푸/스케일러",
      "트리트먼트/팩",
      "두피에센스",
      "헤어에센스",
      "염모제/펌",
      "헤어기기/브러시",
      "스타일링"
    ]
  },
  {
    title: "뷰티소품",
    items: ["메이크업 툴", "아이래쉬 툴", "페이스 툴", "헤어/바디 툴", "데일리 툴"]
  },
  {
    title: "마스크팩",
    items: ["시트팩", "패드", "페이셜팩", "코팩", "패치"]
  },
  {
    title: "선케어",
    items: ["선크림", "선스틱", "선쿠션", "선스프레이/선패치", "태닝/애프터선"]
  },
  {
    title: "메이크업",
    items: ["립메이크업", "베이스메이크업", "아이메이크업"]
  },
  {
    title: "네일",
    items: ["일반네일", "젤네일", "네일팁/스티커", "네일케어/리무버"]
  },
  {
    title: "향수/디퓨저",
    items: ["향수", "미니/고체향수", "홈프래그런스"]
  }
];

const categoryColumns = Array.from({ length: 5 }, (_, index) =>
  [categoryGroups[index], categoryGroups[index + 5]].filter(Boolean)
);

const isCategoryHoverArea = (target: EventTarget | null) => {
  if (!(target instanceof Node)) return false;

  const panel = document.getElementById("categoryPanel");
  const header = document.querySelector("header.site-header");

  return Boolean(header?.contains(target) || panel?.contains(target));
};

type CategoryPanelOverlayProps = {
  onOpenChange: (isOpen: boolean) => void;
};

function CategoryPanelOverlay({ onOpenChange }: CategoryPanelOverlayProps) {
  const handleClose = () => {
    callOriginal("closeCategoryMenu");
    onOpenChange(false);
  };

  return (
    <>
      <div
        className="category-panel-backdrop"
        id="categoryPanelBackdrop"
        onClick={handleClose}
      />
      <aside
        aria-label="카테고리 메뉴"
        className="category-panel"
        id="categoryPanel"
        onMouseEnter={() => {
          callOriginal("openCategoryMenu");
          onOpenChange(true);
        }}
        onMouseLeave={(event) => {
          if (!isCategoryHoverArea(event.relatedTarget)) {
            handleClose();
          }
        }}
      >
        <div className="category-panel__inner">
          {categoryColumns.map((column) => (
            <div
              className="category-panel__column"
              key={column.map((group) => group.title).join("-")}
            >
              {column.map((group) => (
                <section className="category-panel__section" key={group.title}>
                  <Link
                    className="category-panel__title"
                    to={`/category/${encodeURIComponent(group.title)}`}
                    onClick={handleClose}
                  >
                    <span>{group.title}</span>
                  </Link>
                  <div className="category-panel__links">
                    {group.items.map((item) => (
                      <Link
                        to={`/category/${encodeURIComponent(group.title)}`}
                        key={`${group.title}-${item}`}
                        onClick={handleClose}
                      >
                        {item}
                      </Link>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}

export default CategoryPanelOverlay;
