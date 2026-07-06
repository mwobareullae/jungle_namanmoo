const anonymousUserIdKey = "mwbl_anonymous_user_id";
const sessionIdKey = "mwbl_session_id";

const createId = (prefix: string) => {
  const cryptoApi = window.crypto;
  if (cryptoApi?.randomUUID) {
    return `${prefix}_${cryptoApi.randomUUID()}`;
  }
  const randomPart = Math.random().toString(36).slice(2, 12);
  return `${prefix}_${Date.now().toString(36)}_${randomPart}`;
};

const readStorage = (storage: Storage, key: string) => {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
};

const writeStorage = (storage: Storage, key: string, value: string) => {
  try {
    storage.setItem(key, value);
  } catch {
    // Storage can be unavailable in private browsing or strict browser modes.
  }
};

export const getAnonymousUserId = () => {
  const stored = readStorage(window.localStorage, anonymousUserIdKey);
  if (stored) {
    return stored;
  }

  const nextId = createId("anon");
  writeStorage(window.localStorage, anonymousUserIdKey, nextId);
  return nextId;
};

export const getSessionId = () => {
  const stored = readStorage(window.sessionStorage, sessionIdKey);
  if (stored) {
    return stored;
  }

  const nextId = createId("sess");
  writeStorage(window.sessionStorage, sessionIdKey, nextId);
  return nextId;
};

export const createEventId = () => createId("evt");
