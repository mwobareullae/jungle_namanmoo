import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { callOriginal } from "../lib/originalRuntime";

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
  const [categories, setCategories] = useState<Awaited<ReturnType<typeof api.getCategories>>["items"]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    let isMounted = true;
    void api.getCategories()
      .then((response) => {
        if (!isMounted) return;
        setCategories(response.items);
        setHasError(false);
      })
      .catch(() => {
        if (isMounted) setHasError(true);
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, []);

  const categoryGroups = useMemo(() => {
    const groups = new Map<string, { title: string; items: { code: string; name: string }[] }>();
    categories.forEach((category) => {
      const current = groups.get(category.group) ?? { title: category.group_name, items: [] };
      current.items.push({ code: category.code, name: category.name });
      groups.set(category.group, current);
    });
    return Array.from(groups.values());
  }, [categories]);
  const columnCount = Math.ceil(categoryGroups.length / 2);
  const categoryColumns = Array.from({ length: columnCount }, (_, index) =>
    [categoryGroups[index], categoryGroups[index + columnCount]].filter(
      (group): group is (typeof categoryGroups)[number] => Boolean(group)
    )
  );
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
          {isLoading ? <p className="category-panel__state">카테고리를 불러오는 중입니다.</p> : null}
          {!isLoading && hasError ? <p className="category-panel__state">카테고리를 불러오지 못했습니다.</p> : null}
          {!isLoading && !hasError && categoryGroups.length === 0 ? <p className="category-panel__state">표시할 카테고리가 없습니다.</p> : null}
          {!isLoading && !hasError && categoryColumns.map((column, columnIndex) => (
            <div
              className="category-panel__column"
              key={`category-column-${columnIndex}`}
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
                        key={item.code}
                        onClick={handleClose}
                      >
                        {item.name}
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
