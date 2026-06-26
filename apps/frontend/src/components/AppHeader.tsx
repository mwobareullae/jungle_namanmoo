type AppHeaderProps = {
  apiBaseUrl: string;
  onHome: () => void;
};

function AppHeader({ apiBaseUrl, onHome }: AppHeaderProps) {
  return (
    <header className="site-header">
      <button className="brand-mark" type="button" onClick={onHome}>
        muwobareullae
      </button>
      <nav className="header-actions" aria-label="개발 환경 확인">
        <a href={`${apiBaseUrl}/health`}>API</a>
        <span>DEV</span>
      </nav>
    </header>
  );
}

export default AppHeader;
