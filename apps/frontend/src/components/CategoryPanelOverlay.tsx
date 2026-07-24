import { Link } from "react-router-dom";
import { categoryMenu, getCategoryMenuPath } from "../constants/categoryMenu";
import { callOriginal } from "../lib/originalRuntime";

const setInitialInert = (node: HTMLElement | null) => {
  if (node) node.inert = true;
};

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
        aria-hidden="true"
        aria-label="카테고리 메뉴"
        className="category-panel"
        id="categoryPanel"
        ref={setInitialInert}
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
          {categoryMenu.map((group) => (
            <section className="category-panel__section" key={group.slug}>
              <Link
                className="category-panel__title"
                to={getCategoryMenuPath(group.slug)}
                onClick={handleClose}
              >
                <span>{group.name}</span>
              </Link>
              <div className="category-panel__links">
                {group.items.map((item) => (
                  <Link
                    to={getCategoryMenuPath(group.slug, item.slug)}
                    key={item.slug}
                    onClick={handleClose}
                  >
                    {item.name}
                  </Link>
                ))}
              </div>
            </section>
          ))}
        </div>
      </aside>
    </>
  );
}

export default CategoryPanelOverlay;
