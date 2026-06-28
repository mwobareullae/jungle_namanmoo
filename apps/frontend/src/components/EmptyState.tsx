type EmptyStateProps = {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
};

function EmptyState({ title, description, actionLabel, onAction }: EmptyStateProps) {
  return (
    <section className="empty-state" aria-live="polite">
      <p className="eyebrow">Empty</p>
      <h2 className="empty-title">{title}</h2>
      <p className="empty-description">{description}</p>
      {actionLabel && onAction ? (
        <button className="secondary-button" type="button" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </section>
  );
}

export default EmptyState;
