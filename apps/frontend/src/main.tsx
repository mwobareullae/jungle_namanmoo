import React from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";

function App() {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

  return (
    <main className="shell">
      <section className="panel">
        <p className="eyebrow">mwobareullae frontend</p>
        <h1>Hello, 뭐바를래</h1>
        <p>Docker Compose로 실행되는 프론트엔드 최소 개발 서버입니다.</p>
        <a href={`${apiBaseUrl}/health`}>Backend health: {apiBaseUrl}/health</a>
      </section>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
