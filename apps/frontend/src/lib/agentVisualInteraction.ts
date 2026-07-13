export const waitForAgentInteraction = (milliseconds: number) => new Promise<void>((resolve) => {
  window.setTimeout(resolve, milliseconds);
});

export const playAgentClickInteraction = async (target: HTMLElement | null) => {
  if (!target || typeof window === "undefined") return;

  target.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
  await waitForAgentInteraction(180);
  const rect = target.getBoundingClientRect();
  target.classList.add("is-agent-interaction-target");

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    await waitForAgentInteraction(180);
    target.classList.remove("is-agent-interaction-target");
    return;
  }

  const cursor = document.createElement("span");
  cursor.className = "agent-visual-cursor";
  cursor.setAttribute("aria-hidden", "true");
  const destinationX = rect.left + rect.width / 2;
  const destinationY = rect.top + rect.height / 2;
  cursor.style.left = `${Math.min(window.innerWidth - 28, destinationX + 88)}px`;
  cursor.style.top = `${Math.min(window.innerHeight - 28, destinationY + 72)}px`;
  document.body.appendChild(cursor);

  await new Promise<void>((resolve) => window.requestAnimationFrame(() => {
    cursor.style.left = `${destinationX}px`;
    cursor.style.top = `${destinationY}px`;
    resolve();
  }));
  await waitForAgentInteraction(420);
  cursor.classList.add("is-clicking");
  target.classList.add("is-agent-clicked");
  await waitForAgentInteraction(180);
  cursor.remove();
  target.classList.remove("is-agent-clicked", "is-agent-interaction-target");
};
