import { createContext, useCallback, useContext, useEffect, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post, UNAUTHORIZED_EVENT } from "@/api/client";
import type { Me } from "@/api/types";
import { useUi } from "@/state/ui";

interface AuthValue {
  me: Me | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<Me>;
  logout: () => Promise<void>;
  can: (page: string) => boolean;
}

const AuthCtx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const meQ = useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await get<Me>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });

  const clearSession = useCallback(() => {
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    qc.setQueryData(["me"], null);
    useUi.getState().reset();
  }, [qc]);

  useEffect(() => {
    const onUnauthorized = () => {
      if (qc.getQueryData(["me"])) clearSession();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [qc, clearSession]);

  const login = useCallback(
    async (username: string, password: string) => {
      const me = await post<Me>("/auth/login", { username, password });
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      qc.setQueryData(["me"], me);
      return me;
    },
    [qc],
  );

  const logout = useCallback(async () => {
    try {
      await post("/auth/logout", {});
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const me = meQ.data ?? null;
  const can = useCallback((page: string) => !!me?.pages.includes(page), [me]);

  return <AuthCtx.Provider value={{ me, loading: meQ.isLoading, login, logout, can }}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function useMe(): Me {
  const { me } = useAuth();
  if (!me) throw new Error("not signed in");
  return me;
}
