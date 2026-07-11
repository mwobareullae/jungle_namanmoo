function ActivityToast({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div className="activity-toast" role="status" aria-live="polite">
      <span className="activity-toast__dot" />
      {message}
    </div>
  );
}

export default ActivityToast;
