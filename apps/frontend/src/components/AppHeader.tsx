type AppHeaderProps = {
  apiBaseUrl: string;
  isCommunityMode: boolean;
  onNavigate: (path: string) => void;
};

function AppHeader({ apiBaseUrl, isCommunityMode, onNavigate }: AppHeaderProps) {
  const homePath = isCommunityMode ? "/community" : "/";

  return (
    <header className="site-header">
      <button className="brand-mark" type="button" onClick={() => onNavigate(homePath)}>
        뭐바를래
      </button>
      <nav className="header-actions" aria-label="주요 이동">
        <button type="button" onClick={() => onNavigate(homePath)}>
          홈
        </button>
        <button type="button" onClick={() => onNavigate("/search")}>
          검색
        </button>
        <a href={`${apiBaseUrl}/health`}>API</a>
        <span>{isCommunityMode ? "COMMUNITY" : "COMMERCE"}</span>
      </nav>
    </header>
  );
}

export default AppHeader;
