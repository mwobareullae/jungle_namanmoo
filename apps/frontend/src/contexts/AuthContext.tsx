import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL, clearRecommendationCache } from "../lib/api";
import { clearWishlistCache } from "../lib/activityApi";
import { invalidateOrderSummary } from "../lib/orderApi";
import { invalidateMySkinProfileCache } from "../lib/profileApi";
import { skinProfileQueryKey } from "../hooks/useSkinProfileQuery";
import {
  clearAgentChatStorageScope,
  clearLegacyAgentChatStorage,
  getGuestAgentChatStorageScope,
  getUserAgentChatStorageScope,
} from "../lib/agentChatStorage";
import { AuthContext, type AuthUser } from "./authContextValue";

const AUTH_USER_STORAGE_KEY = "mwobareullae.auth.user";
const AUTH_SYNC_CHANNEL_NAME = "mwobareullae.auth.sync";
const AUTH_USER_UPDATED_MESSAGE = "auth-user-updated";
const SESSION_EXPIRED_STORAGE_KEY = "mwobareullae.auth.session-expired";

export const consumeSessionExpiredFlag = (): boolean => {
  try {
    const hadFlag = window.sessionStorage.getItem(SESSION_EXPIRED_STORAGE_KEY) !== null;
    if (hadFlag) {
      window.sessionStorage.removeItem(SESSION_EXPIRED_STORAGE_KEY);
    }
    return hadFlag;
  } catch {
    return false;
  }
};

const markSessionExpired = () => {
  try {
    window.sessionStorage.setItem(SESSION_EXPIRED_STORAGE_KEY, "1");
  } catch {
    // ignore storage failures (e.g. private mode)
  }
};

const isAuthUser = (value: unknown): value is AuthUser => {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    "email" in value &&
    typeof (value as { id: unknown }).id === "number" &&
    typeof (value as { email: unknown }).email === "string"
  );
};

const parseUserResponse = async (response: Response): Promise<AuthUser | null> => {
  const body = (await response.json().catch(() => null)) as unknown;
  if (!body) {
    return null;
  }

  if (isAuthUser(body)) {
    return body;
  }

  if (typeof body === "object" && "user" in body && isAuthUser(body.user)) {
    return body.user;
  }

  return null;
};

const readStoredAuthUser = (): AuthUser | null => {
  try {
    const rawUser = window.sessionStorage.getItem(AUTH_USER_STORAGE_KEY);
    const parsedUser = rawUser ? JSON.parse(rawUser) : null;
    return isAuthUser(parsedUser) ? parsedUser : null;
  } catch {
    return null;
  }
};

const storeAuthUser = (nextUser: AuthUser) => {
  window.sessionStorage.setItem(AUTH_USER_STORAGE_KEY, JSON.stringify(nextUser));
};

const clearStoredAuthUser = () => {
  window.sessionStorage.removeItem(AUTH_USER_STORAGE_KEY);
};

const broadcastAuthUserUpdated = () => {
  if (!("BroadcastChannel" in window)) {
    return;
  }

  const channel = new BroadcastChannel(AUTH_SYNC_CHANNEL_NAME);
  channel.postMessage({ type: AUTH_USER_UPDATED_MESSAGE });
  channel.close();
};

let inFlightMeRequest: Promise<AuthUser | null> | null = null;

// 동시에 여러 트리거(초기 마운트, 탭 포커스 복귀, 다른 탭 로그인 알림)가 겹치면
// /api/me가 중복 호출되던 문제 — 진행 중인 요청이 있으면 그 결과를 공유한다.
const requestAuthenticatedUser = (): Promise<AuthUser | null> => {
  if (inFlightMeRequest) {
    return inFlightMeRequest;
  }

  inFlightMeRequest = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/me`, {
        credentials: "include"
      });

      if (!response.ok) {
        clearStoredAuthUser();
        return null;
      }

      return await parseUserResponse(response);
    } finally {
      inFlightMeRequest = null;
    }
  })();

  return inFlightMeRequest;
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthUser | null>(() => readStoredAuthUser());
  const [isAuthLoading, setIsAuthLoading] = useState(true);
  const userRef = useRef<AuthUser | null>(user);
  // 로그인/로그아웃처럼 확실한 상태 변경이 있을 때마다 올라간다.
  // /api/me 조회가 여러 군데서 겹쳐 나갔다가 뒤늦게 응답이 와도, 그 사이
  // 더 최신 상태 변경이 있었다면(generation 불일치) 오래된 응답은 버린다.
  const authGenerationRef = useRef(0);

  useEffect(() => {
    userRef.current = user;
  }, [user]);

  const applyAuthResult = useCallback(
    (nextUser: AuthUser | null, generation: number, hadUserBefore: boolean) => {
      if (generation !== authGenerationRef.current) {
        return;
      }
      setUser(nextUser);
      if (nextUser) {
        storeAuthUser(nextUser);
      } else {
        clearStoredAuthUser();
        if (hadUserBefore) {
          markSessionExpired();
        }
      }
    },
    []
  );

  const refreshAuthenticatedUser = useCallback(async () => {
    const hadUser = userRef.current !== null;
    const generation = authGenerationRef.current;
    const nextUser = await requestAuthenticatedUser();
    applyAuthResult(nextUser, generation, hadUser);
    return nextUser;
  }, [applyAuthResult]);

  useEffect(() => {
    clearLegacyAgentChatStorage();
  }, []);

  useEffect(() => {
    let isMounted = true;
    const hadStoredUser = readStoredAuthUser() !== null;
    const generation = authGenerationRef.current;

    requestAuthenticatedUser()
      .then((nextUser) => {
        if (!isMounted) {
          return;
        }
        applyAuthResult(nextUser, generation, hadStoredUser);
      })
      .catch(() => {
        if (!isMounted || generation !== authGenerationRef.current) {
          return;
        }
        setUser(null);
        clearStoredAuthUser();
      })
      .finally(() => {
        if (isMounted) {
          setIsAuthLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [applyAuthResult]);

  const setAuthenticatedUser = useCallback((nextUser: AuthUser) => {
    authGenerationRef.current += 1;
    storeAuthUser(nextUser);
    setUser(nextUser);
    broadcastAuthUserUpdated();
  }, []);

  useEffect(() => {
    if (!("BroadcastChannel" in window)) {
      return;
    }

    const channel = new BroadcastChannel(AUTH_SYNC_CHANNEL_NAME);
    channel.onmessage = (event: MessageEvent<unknown>) => {
      const data = event.data;
      if (
        typeof data === "object" &&
        data !== null &&
        "type" in data &&
        data.type === AUTH_USER_UPDATED_MESSAGE
      ) {
        void refreshAuthenticatedUser().catch(() => null);
      }
    };

    return () => channel.close();
  }, [refreshAuthenticatedUser]);

  useEffect(() => {
    const refreshOnVisible = () => {
      if (document.visibilityState === "visible") {
        void refreshAuthenticatedUser().catch(() => null);
      }
    };

    document.addEventListener("visibilitychange", refreshOnVisible);
    return () => document.removeEventListener("visibilitychange", refreshOnVisible);
  }, [refreshAuthenticatedUser]);

  const logout = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/auth/logout`, {
      method: "POST",
      credentials: "include"
    });

    if (!response.ok && response.status !== 401) {
      throw new Error("logout failed");
    }

    authGenerationRef.current += 1;
    const previousUserId = user?.id ?? null;
    if (previousUserId !== null) {
      clearAgentChatStorageScope(getUserAgentChatStorageScope(previousUserId));
    }
    clearAgentChatStorageScope(getGuestAgentChatStorageScope());
    clearLegacyAgentChatStorage();
    clearWishlistCache(previousUserId);
    clearRecommendationCache();
    invalidateOrderSummary(previousUserId);
    invalidateMySkinProfileCache(previousUserId);
    queryClient.removeQueries({ queryKey: skinProfileQueryKey(previousUserId) });
    clearStoredAuthUser();
    setUser(null);
  }, [queryClient, user?.id]);

  const value = useMemo(
    () => ({
      user,
      isAuthLoading,
      setAuthenticatedUser,
      refreshAuthenticatedUser,
      logout
    }),
    [isAuthLoading, logout, refreshAuthenticatedUser, setAuthenticatedUser, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
