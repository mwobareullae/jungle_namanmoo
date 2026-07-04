import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";

const queryClient = new QueryClient();

async function enableMocking() {
<<<<<<< HEAD
  if (import.meta.env.DEV && import.meta.env.VITE_ENABLE_MOCKS === "true") {
=======
  if (import.meta.env.DEV && import.meta.env.VITE_ENABLE_MSW === "true") {
>>>>>>> d76b0a6 (chore(frontend): 피부 테스트 개발 환경 설정 추가)
    const { worker } = await import("./mocks/browser");
    return worker.start();
  }
}

enableMocking().then(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  );
});
