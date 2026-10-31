import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getToken, setToken, SESSION_EXPIRED_EVENT } from "../api/client";
import * as api from "../api/endpoints";
import type { User } from "../types/backend";

type Status = "checking" | "signed-in" | "signed-out";
type AuthMode = "signin" | "signup";

interface AuthValue {
  status: Status;
  user: User | null;
  sessionExpired: boolean;
  dismissExpired: () => void;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (payload: { email: string; password: string; name: string; business_name: string }) => Promise<void>;
  signOut: () => void;
  authModal: { open: boolean; mode: AuthMode; returnTo: string | null };
  openAuth: (mode?: AuthMode, returnTo?: string | null) => void;
  closeAuth: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>(getToken() ? "checking" : "signed-out");
  const [user, setUser] = useState<User | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [authModal, setAuthModal] = useState<AuthValue["authModal"]>({ open: false, mode: "signin", returnTo: null });

  useEffect(() => {
    if (!getToken()) return;
    let active = true;
    api.me()
      .then((value) => { if (active) { setUser(value); setStatus("signed-in"); } })
      .catch(() => { if (active) { setToken(""); setStatus("signed-out"); } });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const onExpired = () => { setToken(""); setUser(null); setStatus("signed-out"); setSessionExpired(true); };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

  const finish = (token: string, value: User) => { setToken(token); setUser(value); setStatus("signed-in"); setSessionExpired(false); };
  const signIn = useCallback(async (email: string, password: string) => {
    const result = await api.login({ email: email.trim().toLowerCase(), password });
    finish(result.access_token, result.user);
  }, []);
  const signUp = useCallback(async (payload: { email: string; password: string; name: string; business_name: string }) => {
    const result = await api.register({ ...payload, email: payload.email.trim().toLowerCase() });
    finish(result.access_token, result.user);
  }, []);
  const signOut = useCallback(() => { setToken(""); setUser(null); setStatus("signed-out"); }, []);
  const openAuth = useCallback((mode: AuthMode = "signin", returnTo: string | null = null) => setAuthModal({ open: true, mode, returnTo }), []);
  const closeAuth = useCallback(() => setAuthModal((current) => ({ ...current, open: false })), []);

  const value = useMemo<AuthValue>(() => ({
    status, user, sessionExpired, dismissExpired: () => setSessionExpired(false),
    signIn, signUp, signOut, authModal, openAuth, closeAuth,
  }), [status, user, sessionExpired, signIn, signUp, signOut, authModal, openAuth, closeAuth]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
