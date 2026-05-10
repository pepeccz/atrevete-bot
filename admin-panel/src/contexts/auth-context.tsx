"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";

interface User {
  username: string;
  role: string;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  const checkAuth = useCallback(async () => {
    // GET /api/admin/auth/me is the SOLE source of truth for authentication state.
    // No localStorage reads, no client-side JWT decoding.
    // isLoading stays true until the response resolves.
    setIsLoading(true);
    try {
      const userData = await api.getMe();
      setUser(userData);
    } catch {
      // 401 (or network error) — treat as unauthenticated.
      // api.ts handles 401 → redirect to /login automatically,
      // but we also clear the user state here for correctness.
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = async (username: string, password: string) => {
    // Server sets the HttpOnly cookie in Set-Cookie; response body has no token.
    await api.login(username, password);
    // Refresh auth state from /auth/me now that the cookie exists.
    await checkAuth();
    // Navigate to the page the user was trying to access, or the dashboard.
    const returnTo = sessionStorage.getItem("returnTo");
    sessionStorage.removeItem("returnTo");
    router.push(returnTo || "/dashboard");
  };

  const logout = () => {
    api.logout();
    setUser(null);
    router.push("/login");
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
