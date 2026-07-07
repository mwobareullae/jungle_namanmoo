const POST_LOGIN_SKIN_TEST_PROMPT_KEY = "mwobareullae.skinTestPrompt.pending";
const SKIN_TEST_PROMPT_DISMISSED_KEY = "mwobareullae.skinTestPrompt.dismissed";

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

export const hasDismissedSkinTestPrompt = () =>
  window.localStorage.getItem(SKIN_TEST_PROMPT_DISMISSED_KEY) === "1";

export const dismissSkinTestPromptPermanently = () => {
  window.localStorage.setItem(SKIN_TEST_PROMPT_DISMISSED_KEY, "1");
};
