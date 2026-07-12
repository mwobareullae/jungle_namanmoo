import { AdminAccessStatus } from "./hooks/useAdminAccess";

// 관리자 페이지 진입 게이트. AdminDashboardPage 전체를 감싸서, 로그인/권한이
// 확인되기 전에는 사이드바·mock 화면 등 어떤 관리자 UI도 노출하지 않는다.

type BadgeTone = "success" | "warning" | "danger" | "neutral" | "review";

const ACCESS_COPY: Record<
  Exclude<AdminAccessStatus, "authenticated">,
  { title: string; message: string; tone: BadgeTone }
> = {
  checking: { title: "확인 중", message: "관리자 권한을 확인하고 있습니다.", tone: "neutral" },
  unauthenticated: {
    title: "로그인이 필요합니다",
    message: "관리자 계정으로 로그인한 뒤 다시 시도해 주세요.",
    tone: "warning"
  },
  forbidden: {
    title: "관리자 권한이 필요합니다",
    message: "이 계정은 관리자 페이지에 접근할 수 없습니다.",
    tone: "danger"
  },
  error: {
    title: "연결 오류",
    message: "접근 권한을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    tone: "danger"
  }
};

type AdminAccessNoticeProps = {
  status: Exclude<AdminAccessStatus, "authenticated">;
  retry: () => void;
};

export function AdminAccessNotice({ status, retry }: AdminAccessNoticeProps) {
  const copy = ACCESS_COPY[status];

  return (
    <main className="admin-shell">
      <section className="admin-main" id="admin-dashboard">
        <section className="admin-panel">
          <div className="admin-panel-header admin-product-header">
            <div>
              <p>관리자</p>
              <h2>뭐바를래 관리자 페이지</h2>
            </div>
          </div>
          <div className={`admin-state-banner ${copy.tone}`}>
            <strong>{copy.title}</strong>
            <span>{copy.message}</span>
          </div>
          {status !== "checking" && (
            <button className="admin-secondary-button" onClick={retry} type="button">
              다시 시도
            </button>
          )}
        </section>
      </section>
    </main>
  );
}
