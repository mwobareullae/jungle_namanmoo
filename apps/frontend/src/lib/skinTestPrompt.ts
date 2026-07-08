const POST_LOGIN_SKIN_TEST_PROMPT_KEY = "mwobareullae.skinTestPrompt.pending";
const SKIN_TEST_PROMPT_DISMISSED_KEY = "mwobareullae.skinTestPrompt.dismissed";
const SKIN_TEST_PROMPT_DISMISS_DURATION_MS = 7 * 24 * 60 * 60 * 1000;

export const markSkinTestPromptPending = () => {
  window.sessionStorage.setItem(POST_LOGIN_SKIN_TEST_PROMPT_KEY, "1");
};

export const consumeSkinTestPromptPending = () => {
  const isPending = window.sessionStorage.getItem(POST_LOGIN_SKIN_TEST_PROMPT_KEY) === "1";

  if (isPending) {
    window.sessionStorage.removeItem(POST_LOGIN_SKIN_TEST_PROMPT_KEY);
  }

  return isPending;
};

export const hasDismissedSkinTestPrompt = () => {
  const dismissedUntil = window.localStorage.getItem(SKIN_TEST_PROMPT_DISMISSED_KEY);

  if (!dismissedUntil) {
    return false;
  }

  if (dismissedUntil === "1") {
    window.localStorage.setItem(
      SKIN_TEST_PROMPT_DISMISSED_KEY,
      String(Date.now() + SKIN_TEST_PROMPT_DISMISS_DURATION_MS)
    );
    return true;
  }

  const dismissedUntilTime = Number(dismissedUntil);

  if (!Number.isFinite(dismissedUntilTime) || dismissedUntilTime <= Date.now()) {
    window.localStorage.removeItem(SKIN_TEST_PROMPT_DISMISSED_KEY);
    return false;
  }

  return true;
};

export const dismissSkinTestPromptForSevenDays = () => {
  window.localStorage.setItem(
    SKIN_TEST_PROMPT_DISMISSED_KEY,
    String(Date.now() + SKIN_TEST_PROMPT_DISMISS_DURATION_MS)
  );
};
