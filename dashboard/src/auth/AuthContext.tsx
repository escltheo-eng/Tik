/**
 * AuthContext — état global de la connexion au core Tik.
 *
 * Expose :
 *   - `apiKey` et `baseUrl` courants (chargés depuis le storage au boot),
 *   - `client`, instance `HttpClient` reconstruite quand l'un des deux change,
 *   - `signIn(baseUrl, apiKey)` : persiste + active la session,
 *   - `signOut()` : purge le storage,
 *   - `loading` : true pendant la lecture initiale du storage.
 *
 * Pas de React Query ni Zustand pour rester simple — on remontera la
 * complexité quand le besoin se présentera (Sessions 3-4).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { HttpClient } from '@/src/api/client';
import { DEFAULT_BASE_URL, STORAGE_KEYS, deleteItem, getItem, setItem } from './storage';

interface AuthState {
  baseUrl: string;
  apiKey: string | null;
  loading: boolean;
  client: HttpClient;
  isAuthenticated: boolean;
  signIn: (baseUrl: string, apiKey: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [baseUrl, setBaseUrlState] = useState<string>(DEFAULT_BASE_URL);
  const [apiKey, setApiKeyState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [storedUrl, storedKey] = await Promise.all([
          getItem(STORAGE_KEYS.baseUrl),
          getItem(STORAGE_KEYS.apiKey),
        ]);
        if (cancelled) return;
        if (storedUrl) setBaseUrlState(storedUrl);
        if (storedKey) setApiKeyState(storedKey);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (newBaseUrl: string, newApiKey: string) => {
    const cleanedUrl = newBaseUrl.trim().replace(/\/+$/, '');
    const cleanedKey = newApiKey.trim();
    await setItem(STORAGE_KEYS.baseUrl, cleanedUrl);
    await setItem(STORAGE_KEYS.apiKey, cleanedKey);
    setBaseUrlState(cleanedUrl);
    setApiKeyState(cleanedKey);
  }, []);

  const signOut = useCallback(async () => {
    await deleteItem(STORAGE_KEYS.apiKey);
    setApiKeyState(null);
  }, []);

  const client = useMemo(
    () => new HttpClient({ baseUrl, apiKey }),
    [baseUrl, apiKey],
  );

  const value = useMemo<AuthState>(
    () => ({
      baseUrl,
      apiKey,
      loading,
      client,
      isAuthenticated: apiKey !== null && apiKey.length > 0,
      signIn,
      signOut,
    }),
    [baseUrl, apiKey, loading, client, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error('useAuth must be used inside <AuthProvider>');
  }
  return ctx;
}
