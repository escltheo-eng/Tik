/**
 * Persistence cross-platform pour les credentials et la config.
 *
 * - Sur natif (iOS / Android) : `expo-secure-store` (Keychain iOS,
 *   EncryptedSharedPreferences Android), donc chiffré au niveau OS.
 * - Sur web : `window.localStorage` (non chiffré). Acceptable pour le
 *   MVP en mode shadow ; à reconsidérer si on déploie le dashboard en
 *   production publique.
 *
 * `expo-secure-store` jette une erreur s'il est appelé sur web, donc le
 * dispatch via `Platform.OS === 'web'` est obligatoire.
 */

import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

const isWeb = Platform.OS === 'web';

export async function getItem(key: string): Promise<string | null> {
  if (isWeb) {
    if (typeof window === 'undefined' || !window.localStorage) return null;
    return window.localStorage.getItem(key);
  }
  return SecureStore.getItemAsync(key);
}

export async function setItem(key: string, value: string): Promise<void> {
  if (isWeb) {
    if (typeof window === 'undefined' || !window.localStorage) return;
    window.localStorage.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

export async function deleteItem(key: string): Promise<void> {
  if (isWeb) {
    if (typeof window === 'undefined' || !window.localStorage) return;
    window.localStorage.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}

export const STORAGE_KEYS = {
  apiKey: 'tik.dashboard.api_key',
  baseUrl: 'tik.dashboard.base_url',
} as const;

export const DEFAULT_BASE_URL = 'http://localhost:8200';
