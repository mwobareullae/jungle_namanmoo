import { createContext } from "react";

export type AuthUser = {
  id: number;
  email: string;
  nickname?: string | null;
  role?: string;
  status?: string;
  created_at?: string | null;
};

export type AuthContextValue = {
  user: AuthUser | null;
  isAuthLoading: boolean;
  setAuthenticatedUser: (user: AuthUser) => void;
  refreshAuthenticatedUser: () => Promise<AuthUser | null>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);
