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

const CATEGORY_GROUP_ORDER = [
  "skincare",
  "cleansing",
  "makeup",
  "bodycare",
  "haircare",
  "men",
  "mask_pack",
  "suncare",
  "fragrance",
  "nail",
  "beauty_tool",
] as const;

const categoryGroupOrder = new Map(CATEGORY_GROUP_ORDER.map((group, index) => [group, index]));
const CATEGORY_PRIMARY_GROUPS = ["skincare", "cleansing", "makeup", "men"] as const;
const CATEGORY_SECONDARY_GROUPS = ["mask_pack", "suncare", "fragrance", "nail", "beauty_tool"] as const;

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
    const groups = new Map<string, { group: string; title: string; items: { code: string; name: string }[] }>();
    categories.forEach((category) => {
      const current = groups.get(category.group) ?? {
        group: category.group,
        title: category.group_name,
        items: [],
      };
      current.items.push({ code: category.code, name: category.name });
      groups.set(category.group, current);
    });
    return Array.from(groups.values())
      .filter((group) => group.title.trim() !== "기타")
      .sort(
        (left, right) =>
          (categoryGroupOrder.get(left.group) ?? Number.MAX_SAFE_INTEGER)
          - (categoryGroupOrder.get(right.group) ?? Number.MAX_SAFE_INTEGER),
      );
  }, [categories]);
  const categoryGridItems = useMemo(() => {
    const groupsByCode = new Map(categoryGroups.map((group) => [group.group, group]));
    const getGroups = (groupCodes: readonly string[]) =>
      groupCodes.flatMap((groupCode) => {
        const group = groupsByCode.get(groupCode);
        return group ? [group] : [];
      });
    const bodyAndHairGroups = getGroups(["bodycare", "haircare"]);
    const items = [
      ...getGroups(CATEGORY_PRIMARY_GROUPS.slice(0, 3)).map((group) => ({ key: group.group, groups: [group] })),
      ...(bodyAndHairGroups.length > 0 ? [{ key: "bodycare-haircare", groups: bodyAndHairGroups }] : []),
      ...getGroups(CATEGORY_PRIMARY_GROUPS.slice(3)).map((group) => ({ key: group.group, groups: [group] })),
      ...getGroups(CATEGORY_SECONDARY_GROUPS).map((group) => ({ key: group.group, groups: [group] })),
    ];
    const usedGroups = new Set(items.flatMap((item) => item.groups.map((group) => group.group)));

    return [
      ...items,
      ...categoryGroups
        .filter((group) => !usedGroups.has(group.group))
        .map((group) => ({ key: group.group, groups: [group] })),
    ];
  }, [categoryGroups]);
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
          {!isLoading && !hasError && categoryGridItems.length === 0 ? <p className="category-panel__state">표시할 카테고리가 없습니다.</p> : null}
          {!isLoading && !hasError && categoryGridItems.map((item) => (
            <div
              className={item.groups.length > 1 ? "category-panel__section-stack" : undefined}
              key={item.key}
            >
              {item.groups.map((group) => (
                <section className="category-panel__section" key={group.group}>
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
