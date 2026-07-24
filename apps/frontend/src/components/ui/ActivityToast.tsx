type ActivityToastProps = {
  message: string;
  tone?: "default" | "error";
};

function ActivityToast({ message, tone = "default" }: ActivityToastProps) {
  if (!message) return null;
  return (
    <div
      className={`activity-toast${tone === "error" ? " activity-toast--error" : ""}`}
      role={tone === "error" ? "alert" : "status"}
      aria-live={tone === "error" ? "assertive" : "polite"}
    >
      <span className="activity-toast__dot" />
      {message}
    </div>
  );
}

export default ActivityToast;
