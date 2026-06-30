import type { KeyboardEvent } from "react";
import { callOriginal } from "../lib/originalRuntime";
import type { Sensitivity, SkinType } from "../types/recommendation";

const setSearch = (text: string) => callOriginal("setSearch", text);

type HomeHeroProps = {
  initialQuery?: string;
  initialProfile?: {
    skin: SkinType;
    sensitivity: Sensitivity;
  };
};

function HomeHero({
  initialQuery = "",
  initialProfile = {
    skin: "수부지",
    sensitivity: "보통",
  },
}: HomeHeroProps) {
  const handleSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    callOriginal("handleSearch", event);
  };

  return (
    <section className="hero">
      <div className="hero-inner">
        <h1>
          내 피부 고민에 맞는
          <br />
          <em>최적의 화장품 추천</em>
        </h1>
        <p>
          피부 고민을 입력하면 성분 효능 근거를 바탕으로
          <br />
          지금 필요한 제품을 찾아드려요
        </p>

        <div className="search-container">
          <div className="search-combo">
            <div className="search-box" id="searchBox">
              <div className="search-icon">
                <svg
                  fill="none"
                  height="18"
                  stroke="#94e0f8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  viewBox="0 0 24 24"
                  width="18"
                >
                  <circle cx="11" cy="11" r="8" />
                  <path d="m21 21-4.35-4.35" />
                </svg>
              </div>
              <button
                className="search-profile-chip"
                id="searchProfileChip"
                onClick={() => callOriginal("openSearchSuggestions")}
                type="button"
              >
                {initialProfile.skin} · {initialProfile.sensitivity}
              </button>
              <input
                defaultValue={initialQuery}
                id="searchInput"
                onKeyDown={handleSearchKey}
                placeholder="모공이 넓고 번들거려요"
                type="text"
              />
              <button className="search-btn" onClick={() => callOriginal("doSearch")} type="button">
                <svg
                  fill="none"
                  height="14"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2.5"
                  viewBox="0 0 24 24"
                  width="14"
                >
                  <path d="m22 2-7 20-4-9-9-4z" />
                </svg>
                추천 찾기
              </button>
            </div>

            <div
              aria-label="최근 고민과 피부 조건"
              className="search-suggest-panel"
              id="searchSuggestPanel"
            >
              <div className="suggest-section">
                <div className="suggest-header">
                  <span>최근 고민</span>
                  <button
                    className="recent-clear"
                    id="recentClearButton"
                    onClick={(event) => callOriginal("clearRecentConcerns", event)}
                    type="button"
                  >
                    전체 삭제
                  </button>
                </div>
                <div className="recent-list" id="recentConcernList" />
              </div>

              <div className="suggest-section">
                <div className="profile-picker-grid">
                  <div className="profile-picker-group">
                    <span className="profile-picker-label">피부 타입</span>
                    <div aria-label="피부 타입" className="profile-segments skin" role="radiogroup">
                      {["건성", "지성", "복합성", "수부지", "중성"].map((skinType) => (
                        <button
                          className={`profile-option${skinType === initialProfile.skin ? " active" : ""}`}
                          data-profile="skin"
                          data-value={skinType}
                          key={skinType}
                          onClick={() => callOriginal("selectProfileOption", "skin", skinType)}
                          type="button"
                        >
                          {skinType}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="profile-picker-group">
                    <span className="profile-picker-label">민감도</span>
                    <div
                      aria-label="민감도"
                      className="profile-segments sensitivity"
                      role="radiogroup"
                    >
                      {["낮음", "보통", "높음"].map((sensitivity) => (
                        <button
                          className={`profile-option${sensitivity === initialProfile.sensitivity ? " active" : ""}`}
                          data-profile="sensitivity"
                          data-value={sensitivity}
                          key={sensitivity}
                          onClick={() => callOriginal("selectProfileOption", "sensitivity", sensitivity)}
                          type="button"
                        >
                          {sensitivity}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="suggest-actions">
                  <span className="profile-summary" id="profileSummary">
                    {initialProfile.skin} · 민감도 {initialProfile.sensitivity} 기준으로 추천
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="search-examples">
            <span className="example-chip" onClick={() => setSearch("모공이 넓고 피지가 많아요")}>
              모공이 넓고 피지가 많아요
            </span>
            <span className="example-chip" onClick={() => setSearch("건조하고 주름이 걱정돼요")}>
              건조하고 주름이 걱정돼요
            </span>
            <span className="example-chip" onClick={() => setSearch("색소침착과 잡티가 있어요")}>
              색소침착과 잡티가 있어요
            </span>
            <span className="example-chip" onClick={() => setSearch("민감하고 자주 붉어져요")}>
              민감하고 자주 붉어져요
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

export default HomeHero;
