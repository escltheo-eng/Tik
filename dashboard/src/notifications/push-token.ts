/**
 * Helpers pour les notifications push Expo.
 *
 * Limitations connues :
 *   - **Web** : pas de support Expo Push, on retourne null. (On pourrait
 *     utiliser l'API `Notification` du navigateur, mais ça nécessite HTTPS
 *     hors localhost et n'est pas couplé au système Expo Push — hors scope.)
 *   - **Expo Go (SDK 53+)** : Expo a retiré le support des push remotes
 *     dans Expo Go. Le token est techniquement récupérable mais ne reçoit
 *     plus rien. Pour des push réels, il faut un build EAS / dev client.
 *
 * Cette infra est donc préparée mais sera vraiment utile quand on fera
 * un build EAS dans une future session.
 */

import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { STORAGE_KEYS, getItem, setItem } from '@/src/auth/storage';

export const PUSH_TOKEN_STORAGE_KEY = 'tik.dashboard.push_token';

export interface PushTokenInfo {
  token: string | null;
  permissionStatus: 'granted' | 'denied' | 'undetermined' | 'unsupported';
  reason?: string;
}

export async function ensurePushPermissions(): Promise<PushTokenInfo['permissionStatus']> {
  if (Platform.OS === 'web') return 'unsupported';

  const existing = await Notifications.getPermissionsAsync();
  if (existing.status === 'granted') return 'granted';

  const requested = await Notifications.requestPermissionsAsync();
  if (requested.status === 'granted') return 'granted';
  return requested.status === 'denied' ? 'denied' : 'undetermined';
}

/**
 * Renvoie le projectId Expo, requis par `getExpoPushTokenAsync` côté SDK 54+.
 * Lu depuis app.json (`extra.eas.projectId`) ou Constants.easConfig.
 */
function readProjectId(): string | null {
  const fromExpoConfig = (Constants.expoConfig as { extra?: Record<string, unknown> } | null)?.extra;
  const fromEasConfig = (Constants as unknown as { easConfig?: { projectId?: string } }).easConfig;
  const easExtra = fromExpoConfig?.eas as { projectId?: string } | undefined;
  return easExtra?.projectId ?? fromEasConfig?.projectId ?? null;
}

export async function fetchExpoPushToken(): Promise<PushTokenInfo> {
  if (Platform.OS === 'web') {
    return {
      token: null,
      permissionStatus: 'unsupported',
      reason: 'Web ne supporte pas Expo Push — utiliser un build natif (EAS).',
    };
  }

  const status = await ensurePushPermissions();
  if (status !== 'granted') {
    return {
      token: null,
      permissionStatus: status,
      reason:
        status === 'denied'
          ? 'Permission refusée par l’utilisateur.'
          : 'Permission non encore décidée.',
    };
  }

  const projectId = readProjectId();
  try {
    const token = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined,
    );
    await setItem(PUSH_TOKEN_STORAGE_KEY, token.data);
    return { token: token.data, permissionStatus: 'granted' };
  } catch (err) {
    return {
      token: null,
      permissionStatus: 'granted',
      reason: `Echec récupération token : ${(err as Error).message}`,
    };
  }
}

export async function getStoredPushToken(): Promise<string | null> {
  return getItem(PUSH_TOKEN_STORAGE_KEY);
}

// Garde le STORAGE_KEYS source pour ne pas dupliquer la déclaration.
export { STORAGE_KEYS };
