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
import { isTokenExpired, decodeToken } from "@/lib/auth";

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
    const token = localStorage.getItem("admin_token");

    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }

    // If token is expired, clear it
    if (isTokenExpired(token)) {
      localStorage.removeItem("admin_token");
      setUser(null);
      setIsLoading(false);
      return;
    }

    // Token exists and is not expired - extract user from token
    const payload = decodeToken(token);
    if (!payload) {
      localStorage.removeItem("admin_token");
      setUser(null);
      setIsLoading(false);
      return;
    }

    // Set user from token immediately (optimistic)
    setUser({ username: payload.sub, role: "admin" });

    // Validate with backend (but don't logout on network errors)
    try {
      const userData = await api.getMe();
      setUser(userData);
    } catch (error) {
      // Only clear token on 401 Unauthorized (invalid/expired token)
      // Keep session on network errors (backend down, etc.)
      if (error instanceof Error && error.message.includes("401")) {
        localStorage.removeItem("admin_token");
        setUser(null);
      }
      // Otherwise, keep the session from the token
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const login = async (username: string, password: string) => {
    const response = await api.login(username, password);
    const payload = decodeToken(response.access_token);
    if (payload) {
      setUser({ username: payload.sub, role: "admin" });
    }
    // Volver a la URL original o al dashboard
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
