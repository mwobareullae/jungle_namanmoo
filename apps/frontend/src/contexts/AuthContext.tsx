import { useCallback, useEffect, useMemo, useState } from "react";
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

const requestAuthenticatedUser = async (): Promise<AuthUser | null> => {
  const response = await fetch(`${API_BASE_URL}/me`, {
    credentials: "include"
  });

  if (!response.ok) {
    clearStoredAuthUser();
    return null;
  }

  return parseUserResponse(response);
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthUser | null>(() => readStoredAuthUser());
  const [isAuthLoading, setIsAuthLoading] = useState(true);

  const refreshAuthenticatedUser = useCallback(async () => {
    const nextUser = await requestAuthenticatedUser();
    setUser(nextUser);
    if (nextUser) {
      storeAuthUser(nextUser);
    } else {
      clearStoredAuthUser();
    }
    return nextUser;
  }, []);

  useEffect(() => {
    clearLegacyAgentChatStorage();
  }, []);

  useEffect(() => {
    let isMounted = true;

    requestAuthenticatedUser()
      .then((nextUser) => {
        if (!isMounted) {
          return;
        }

        setUser(nextUser);
        if (nextUser) {
          storeAuthUser(nextUser);
        } else {
          clearStoredAuthUser();
        }
      })
      .catch(() => {
        if (!isMounted) {
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
  }, []);

  const setAuthenticatedUser = useCallback((nextUser: AuthUser) => {
    storeAuthUser(nextUser);
    setUser(nextUser);
  }, []);

  const logout = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/auth/logout`, {
      method: "POST",
      credentials: "include"
    });

    if (!response.ok && response.status !== 401) {
      throw new Error("logout failed");
    }

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
