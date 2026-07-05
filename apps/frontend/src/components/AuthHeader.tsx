function AuthHeader() {
  const defaultSectionHref = "/#defaultSection";

  return (
    <header className="border-b border-[rgba(0,0,0,0.07)] bg-white/90 px-5 font-['GmarketSans',system-ui,sans-serif] before:fixed before:top-0 before:left-0 before:z-10 before:h-[5px] before:w-full before:bg-[#94e0f8]">
      <div className="mx-auto flex h-16 w-full max-w-[1280px] items-center gap-8">
        <a
          className="shrink-0 font-['GmarketSans',system-ui,sans-serif] text-[20px] leading-[1.4] font-medium text-[#222222] no-underline"
          href="/"
        >
          뭐바를래
        </a>
        <nav
          aria-label="주요 메뉴"
          className="hidden min-w-0 flex-1 items-center gap-7 text-[14px] leading-[1.4] font-normal text-[#55585d] md:flex"
        >
          <a className="no-underline hover:text-[#1A1A1A]" href={defaultSectionHref}>
            신상품
          </a>
          <a className="no-underline hover:text-[#1A1A1A]" href={defaultSectionHref}>
            베스트
          </a>
          <a className="no-underline hover:text-[#1A1A1A]" href={defaultSectionHref}>
            스킨케어
          </a>
          <a className="no-underline hover:text-[#1A1A1A]" href={defaultSectionHref}>
            메이크업
          </a>
          <a className="no-underline hover:text-[#1A1A1A]" href={defaultSectionHref}>
            헤어/바디
          </a>
          <a className="no-underline hover:text-[#1A1A1A]" href={defaultSectionHref}>
            브랜드
          </a>
          <a
            className="relative font-bold text-[#0B2A3A] no-underline after:absolute after:right-0 after:-bottom-[25px] after:left-0 after:h-[3px] after:rounded-[3px] after:bg-[#94E0F8]"
            href="/skin-test"
          >
            맞춤 추천
          </a>
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-3">
          <a
            aria-label="검색"
            className="hidden h-9 w-9 place-items-center rounded-[14px] text-[#55585d] no-underline hover:bg-[rgba(148,224,248,0.16)] hover:text-[#1A1A1A] sm:grid"
            href="/search"
          >
            <svg
              fill="none"
              height="18"
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              viewBox="0 0 24 24"
              width="18"
            >
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
          </a>
          <a
            className="text-[14px] leading-none font-medium text-[#333333] no-underline hover:text-[#1A1A1A]"
            href="/login"
          >
            로그인
          </a>
        </div>
      </div>
    </header>
  );
}

export default AuthHeader;
