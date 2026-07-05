import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { API_BASE_URL } from "../lib/api";
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
    return readStoredAuthUser();
  }

  return parseUserResponse(response);
};

export function AuthProvider({ children }: { children: ReactNode }) {
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

    clearStoredAuthUser();
    setUser(null);
  }, []);

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
