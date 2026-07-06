const anonymousUserIdKey = "mwbl_anonymous_user_id";
const sessionIdKey = "mwbl_session_id";

const createId = (prefix: string) => {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}_${crypto.randomUUID()}`;
  }

  return `${prefix}_${Math.random().toString(36).slice(2)}_${Date.now().toString(36)}`;
};

const getOrCreateStorageId = (key: string, prefix: string) => {
  if (typeof window === "undefined") {
    return createId(prefix);
  }

  const storedValue = window.localStorage.getItem(key);
  if (storedValue) {
    return storedValue;
  }

  const nextValue = createId(prefix);
  window.localStorage.setItem(key, nextValue);
  return nextValue;
};

export const createEventId = () => createId("evt");

export const getAnonymousUserId = () => getOrCreateStorageId(anonymousUserIdKey, "anon");

export const getSessionId = () => getOrCreateStorageId(sessionIdKey, "sess");
