import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Collapsible } from '@/components/ui/collapsible';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { HttpClient } from '@/src/api/client';
import { getHealth, listEntities } from '@/src/api/endpoints';
import { AuthError, NetworkError, TikError } from '@/src/api/errors';
import { useAuth } from '@/src/auth/AuthContext';
import { GLOSSARY } from '@/src/glossary';
import { fetchExpoPushToken, getStoredPushToken, type PushTokenInfo } from '@/src/notifications/push-token';
import pkg from '../../package.json';

const APP_VERSION = pkg.version;

function maskApiKey(key: string | null): string {
  if (!key) return '—';
  if (key.length <= 8) return '••••';
  return `${key.slice(0, 4)}…${key.slice(-4)}`;
}

function GlossaryRow({ entryKey }: { entryKey: keyof typeof GLOSSARY }) {
  const entry = GLOSSARY[entryKey];
  if (!entry) return null;
  return (
    <View style={styles.glossaryRow}>
      <ThemedText style={styles.glossaryTerm}>{entry.term}</ThemedText>
      <ThemedText style={styles.glossaryShort}>{entry.short}</ThemedText>
      {entry.ref ? (
        <ThemedText style={styles.glossaryRef}>— {entry.ref}</ThemedText>
      ) : null}
    </View>
  );
}

export default function ConfigScreen() {
  const insets = useSafeAreaInsets();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];
  const { baseUrl, apiKey, signIn, signOut } = useAuth();

  const [editing, setEditing] = useState(false);
  const [draftBaseUrl, setDraftBaseUrl] = useState(baseUrl);
  const [draftApiKey, setDraftApiKey] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [updateSuccess, setUpdateSuccess] = useState<string | null>(null);

  const [healthInfo, setHealthInfo] = useState<{ version: string; env: string } | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [pushToken, setPushToken] = useState<string | null>(null);
  const [pushStatus, setPushStatus] = useState<PushTokenInfo['permissionStatus']>('undetermined');
  const [pushReason, setPushReason] = useState<string | null>(null);
  const [pushLoading, setPushLoading] = useState(false);

  useEffect(() => {
    setDraftBaseUrl(baseUrl);
  }, [baseUrl]);

  useEffect(() => {
    let cancelled = false;
    if (!apiKey) return;
    void (async () => {
      try {
        const probe = new HttpClient({ baseUrl, apiKey });
        const data = await getHealth(probe);
        if (!cancelled) {
          setHealthInfo({ version: data.version, env: data.env });
          setHealthError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setHealthError((err as Error).message);
          setHealthInfo(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [baseUrl, apiKey]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const stored = await getStoredPushToken();
      if (!cancelled) setPushToken(stored);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onSaveCredentials = async () => {
    if (!draftBaseUrl.trim() || !draftApiKey.trim()) {
      setUpdateError('URL et clé API requises.');
      return;
    }
    setSubmitting(true);
    setUpdateError(null);
    setUpdateSuccess(null);
    try {
      const probe = new HttpClient({ baseUrl: draftBaseUrl.trim(), apiKey: draftApiKey.trim() });
      await getHealth(probe);
      await listEntities(probe);
      await signIn(draftBaseUrl.trim(), draftApiKey.trim());
      setEditing(false);
      setDraftApiKey('');
      setUpdateSuccess('Credentials mis à jour avec succès.');
    } catch (err) {
      let msg: string;
      if (err instanceof AuthError) msg = 'Clé API refusée par le core (401/403).';
      else if (err instanceof NetworkError) msg = `Core injoignable : ${err.message}`;
      else if (err instanceof TikError) msg = err.message;
      else msg = (err as Error).message;
      setUpdateError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const onTestConnection = async () => {
    setSubmitting(true);
    setUpdateError(null);
    setUpdateSuccess(null);
    try {
      const probe = new HttpClient({ baseUrl, apiKey });
      const data = await getHealth(probe);
      setUpdateSuccess(`Core joignable : v${data.version} env ${data.env}`);
    } catch (err) {
      setUpdateError(`Erreur de connexion : ${(err as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const onActivatePush = async () => {
    setPushLoading(true);
    setPushReason(null);
    const info = await fetchExpoPushToken();
    setPushStatus(info.permissionStatus);
    setPushToken(info.token);
    setPushReason(info.reason ?? null);
    setPushLoading(false);
  };

  const inputStyle = [
    styles.input,
    {
      color: palette.text,
      borderColor: palette.icon,
      backgroundColor: colorScheme === 'dark' ? '#1c2024' : '#fafafa',
    },
  ];

  return (
    <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 8 }]}>
      <View style={styles.header}>
        <ThemedText type="title">Config</ThemedText>
        <ThemedText style={styles.subtitle}>
          Connexion au core, notifications, version et déconnexion.
        </ThemedText>
      </View>

      <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
        <ThemedText type="subtitle">Connexion au core</ThemedText>

        {!editing ? (
          <>
            <ThemedView style={[styles.kv, { backgroundColor: 'transparent' }]}>
              <ThemedText style={styles.kvLabel}>URL</ThemedText>
              <ThemedText style={styles.kvValue}>{baseUrl}</ThemedText>
            </ThemedView>
            <ThemedView style={[styles.kv, { backgroundColor: 'transparent' }]}>
              <ThemedText style={styles.kvLabel}>Clé API</ThemedText>
              <ThemedText style={styles.kvValue}>{maskApiKey(apiKey)}</ThemedText>
            </ThemedView>

            <View style={styles.btnRow}>
              <Pressable
                onPress={() => void onTestConnection()}
                disabled={submitting}
                style={({ pressed }) => [
                  styles.secondaryBtn,
                  { borderColor: palette.icon, opacity: pressed || submitting ? 0.6 : 1 },
                ]}>
                {submitting ? (
                  <ActivityIndicator size="small" />
                ) : (
                  <ThemedText style={{ color: palette.text }}>Tester la connexion</ThemedText>
                )}
              </Pressable>
              <Pressable
                onPress={() => {
                  setEditing(true);
                  setUpdateError(null);
                  setUpdateSuccess(null);
                }}
                style={({ pressed }) => [
                  styles.primaryBtn,
                  { backgroundColor: palette.tint, opacity: pressed ? 0.7 : 1 },
                ]}>
                <ThemedText style={styles.primaryLabel}>Modifier</ThemedText>
              </Pressable>
            </View>
          </>
        ) : (
          <>
            <ThemedView style={[styles.field, { backgroundColor: 'transparent' }]}>
              <ThemedText style={styles.kvLabel}>URL</ThemedText>
              <TextInput
                value={draftBaseUrl}
                onChangeText={setDraftBaseUrl}
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="url"
                placeholderTextColor={palette.icon}
                style={inputStyle}
                editable={!submitting}
              />
            </ThemedView>
            <ThemedView style={[styles.field, { backgroundColor: 'transparent' }]}>
              <ThemedText style={styles.kvLabel}>Nouvelle clé API</ThemedText>
              <TextInput
                value={draftApiKey}
                onChangeText={setDraftApiKey}
                autoCapitalize="none"
                autoCorrect={false}
                secureTextEntry
                placeholder="tik_xxxxxxxxxxxx"
                placeholderTextColor={palette.icon}
                style={inputStyle}
                editable={!submitting}
              />
            </ThemedView>

            <View style={styles.btnRow}>
              <Pressable
                onPress={() => {
                  setEditing(false);
                  setDraftBaseUrl(baseUrl);
                  setDraftApiKey('');
                  setUpdateError(null);
                }}
                disabled={submitting}
                style={({ pressed }) => [
                  styles.secondaryBtn,
                  { borderColor: palette.icon, opacity: pressed || submitting ? 0.6 : 1 },
                ]}>
                <ThemedText style={{ color: palette.text }}>Annuler</ThemedText>
              </Pressable>
              <Pressable
                onPress={() => void onSaveCredentials()}
                disabled={submitting}
                style={({ pressed }) => [
                  styles.primaryBtn,
                  { backgroundColor: palette.tint, opacity: pressed || submitting ? 0.7 : 1 },
                ]}>
                {submitting ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <ThemedText style={styles.primaryLabel}>Enregistrer</ThemedText>
                )}
              </Pressable>
            </View>
          </>
        )}

        {updateError ? (
          <ThemedText style={styles.errorText}>{updateError}</ThemedText>
        ) : updateSuccess ? (
          <ThemedText style={styles.successText}>{updateSuccess}</ThemedText>
        ) : null}
      </ThemedView>

      <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
        <ThemedText type="subtitle">Notifications push</ThemedText>
        <ThemedText style={styles.muted}>
          {Platform.OS === 'web'
            ? 'Push non disponible en web. Utiliser un build natif (EAS) pour activer.'
            : 'Récupère un token Expo Push pour recevoir les alertes hors-app. Nécessite un build natif (Expo Go ne supporte plus le push remote depuis SDK 53).'}
        </ThemedText>

        <ThemedView style={[styles.kv, { backgroundColor: 'transparent' }]}>
          <ThemedText style={styles.kvLabel}>Statut</ThemedText>
          <ThemedText style={styles.kvValue}>{pushStatus}</ThemedText>
        </ThemedView>
        <ThemedView style={[styles.kv, { backgroundColor: 'transparent' }]}>
          <ThemedText style={styles.kvLabel}>Token</ThemedText>
          <ThemedText style={styles.kvValue}>
            {pushToken ? `${pushToken.slice(0, 24)}…` : '—'}
          </ThemedText>
        </ThemedView>

        {pushReason ? <ThemedText style={styles.muted}>{pushReason}</ThemedText> : null}

        <Pressable
          onPress={() => void onActivatePush()}
          disabled={pushLoading || Platform.OS === 'web'}
          style={({ pressed }) => [
            styles.primaryBtn,
            {
              backgroundColor: palette.tint,
              opacity: pressed || pushLoading || Platform.OS === 'web' ? 0.5 : 1,
            },
          ]}>
          {pushLoading ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <ThemedText style={styles.primaryLabel}>
              {pushToken ? 'Régénérer le token' : 'Activer les notifications'}
            </ThemedText>
          )}
        </Pressable>
      </ThemedView>

      <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
        <ThemedText type="subtitle">Glossaire</ThemedText>
        <ThemedText style={styles.muted}>
          Vocabulaire technique Tik. Tape l&apos;icône ? à côté d&apos;un terme dans
          l&apos;app pour voir sa définition rapide.
        </ThemedText>

        <Collapsible title="Scoring du signal">
          <ThemedView style={[styles.glossaryList, { backgroundColor: 'transparent' }]}>
            {(['veracity', 'conviction', 'combinedBias', 'dispersion', 'seuil'] as const).map((k) => (
              <GlossaryRow key={k} entryKey={k} />
            ))}
          </ThemedView>
        </Collapsible>

        <Collapsible title="Sources et preuves">
          <ThemedView style={[styles.glossaryList, { backgroundColor: 'transparent' }]}>
            {(['sourceScores', 'evidence', 'triggers', 'counterScenarios'] as const).map((k) => (
              <GlossaryRow key={k} entryKey={k} />
            ))}
          </ThemedView>
        </Collapsible>

        <Collapsible title="Anti fake-news et fiabilité">
          <ThemedView style={[styles.glossaryList, { backgroundColor: 'transparent' }]}>
            {(['afn'] as const).map((k) => (
              <GlossaryRow key={k} entryKey={k} />
            ))}
          </ThemedView>
        </Collapsible>

        <Collapsible title="Track record et horizons">
          <ThemedView style={[styles.glossaryList, { backgroundColor: 'transparent' }]}>
            {(['trackRecord', 'horizon'] as const).map((k) => (
              <GlossaryRow key={k} entryKey={k} />
            ))}
          </ThemedView>
        </Collapsible>

        <Collapsible title="Workflow et discipline">
          <ThemedView style={[styles.glossaryList, { backgroundColor: 'transparent' }]}>
            {(['outcome', 'hypothesis', 'advisory', 'gardeFou2bis', 'shadow'] as const).map((k) => (
              <GlossaryRow key={k} entryKey={k} />
            ))}
          </ThemedView>
        </Collapsible>
      </ThemedView>

      <ThemedView style={[styles.card, { borderColor: palette.icon }]}>
        <ThemedText type="subtitle">À propos</ThemedText>
        <ThemedView style={[styles.kv, { backgroundColor: 'transparent' }]}>
          <ThemedText style={styles.kvLabel}>Dashboard</ThemedText>
          <ThemedText style={styles.kvValue}>tik-dashboard v{APP_VERSION}</ThemedText>
        </ThemedView>
        <ThemedView style={[styles.kv, { backgroundColor: 'transparent' }]}>
          <ThemedText style={styles.kvLabel}>Core</ThemedText>
          <ThemedText style={styles.kvValue}>
            {healthInfo
              ? `v${healthInfo.version} · env ${healthInfo.env}`
              : healthError
              ? `Erreur : ${healthError}`
              : '—'}
          </ThemedText>
        </ThemedView>
        <ThemedView style={[styles.kv, { backgroundColor: 'transparent' }]}>
          <ThemedText style={styles.kvLabel}>Plateforme</ThemedText>
          <ThemedText style={styles.kvValue}>{Platform.OS}</ThemedText>
        </ThemedView>
        <ThemedView style={[styles.kv, { backgroundColor: 'transparent' }]}>
          <ThemedText style={styles.kvLabel}>Mode</ThemedText>
          <ThemedText style={styles.kvValue}>SHADOW (lecture seule, ADR-003)</ThemedText>
        </ThemedView>

        <ThemedView style={[styles.aboutBody, { backgroundColor: 'transparent' }]}>
          <ThemedText style={styles.aboutIntro}>
            Tik est une plateforme OSINT modulaire qui agrège des données multi-sources,
            score leur crédibilité et produit des signaux pondérés sur 3 horizons en parallèle
            (flash, swing, macro).
          </ThemedText>

          <Collapsible title="Que fait ce dashboard ?">
            <ThemedText>
              Cette application est en LECTURE SEULE. Elle se connecte au core Tik via HTTP REST
              et WebSocket pour visualiser les signaux en temps réel. Elle ne passe jamais d&apos;ordre
              ni n&apos;altère les bots Zeta/Totem (cf. ADR-003).
            </ThemedText>
          </Collapsible>

          <Collapsible title="Architecture en 3 couches">
            <ThemedText>
              • Couche 1 — Core engine (FastAPI) : source de vérité unique{'\n'}
              • Couche 2 — SDK Python (tik-sdk) : utilisé par les bots backend Zeta/Totem{'\n'}
              • Couche 3 — Dashboard Expo : ce que vous regardez (web et mobile)
            </ThemedText>
          </Collapsible>

          <Collapsible title="Garde-fous opérationnels">
            <ThemedText>
              • Mode SHADOW obligatoire (3 mois minimum) avant connexion réelle Tik ↔ Zeta{'\n'}
              • Budget de test limité à 5 % du capital pendant 1 mois après le mode shadow{'\n'}
              • Aucun bypass du guard V01-V15 côté Zeta — ADR-003
            </ThemedText>
          </Collapsible>

          <Collapsible title="Paranoïa contrôlée">
            <ThemedText>
              Chaque signal Tik livre systématiquement : une hypothèse principale, au moins
              2 contre-scénarios avec leur probabilité estimée, des preuves (evidence) avec
              leur source et leur score de crédibilité, et des triggers techniques pondérés.
            </ThemedText>
          </Collapsible>
        </ThemedView>
      </ThemedView>

      <Pressable
        onPress={() => void signOut()}
        style={({ pressed }) => [
          styles.signOutBtn,
          { borderColor: '#c0392b', opacity: pressed ? 0.6 : 1 },
        ]}>
        <ThemedText style={{ color: '#c0392b', fontWeight: '600' }}>Se déconnecter</ThemedText>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: {
    paddingHorizontal: 16,
    paddingBottom: 32,
    gap: 12,
  },
  header: {
    gap: 4,
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 13,
    opacity: 0.7,
  },
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  kv: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  kvLabel: {
    fontSize: 13,
    opacity: 0.6,
  },
  kvValue: {
    fontSize: 13,
    flexShrink: 1,
    textAlign: 'right',
  },
  field: {
    gap: 4,
  },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
  },
  btnRow: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 8,
  },
  primaryBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryLabel: {
    color: '#ffffff',
    fontWeight: '600',
  },
  secondaryBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
  },
  errorText: {
    color: '#c0392b',
    fontSize: 13,
  },
  successText: {
    color: '#27ae60',
    fontSize: 13,
  },
  muted: {
    fontSize: 12,
    opacity: 0.7,
    lineHeight: 18,
  },
  signOutBtn: {
    marginTop: 12,
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
    borderWidth: 1,
  },
  aboutBody: {
    marginTop: 8,
    gap: 4,
  },
  aboutIntro: {
    fontSize: 13,
    opacity: 0.85,
    lineHeight: 20,
    marginBottom: 4,
  },
  glossaryList: {
    gap: 12,
    paddingTop: 4,
  },
  glossaryRow: {
    gap: 2,
  },
  glossaryTerm: {
    fontSize: 14,
    fontWeight: '700',
  },
  glossaryShort: {
    fontSize: 13,
    opacity: 0.85,
    lineHeight: 18,
  },
  glossaryRef: {
    fontSize: 11,
    opacity: 0.55,
    fontStyle: 'italic',
  },
});
