import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { CosmicCollapsible } from '@/components/cosmic/cosmic-collapsible';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import { Fonts } from '@/constants/theme';
import { HttpClient } from '@/src/api/client';
import { getHealth, listEntities } from '@/src/api/endpoints';
import { AuthError, NetworkError, TikError } from '@/src/api/errors';
import { useAuth } from '@/src/auth/AuthContext';
import { useFlashCardSetting } from '@/src/flash/flashCardSetting';
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
      <Text style={styles.glossaryTerm}>{entry.term}</Text>
      <Text style={styles.glossaryShort}>{entry.short}</Text>
      {entry.ref ? <Text style={styles.glossaryRef}>— {entry.ref}</Text> : null}
    </View>
  );
}

export default function ConfigScreen() {
  const insets = useSafeAreaInsets();
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

  const [flashCardEnabled, setFlashCardEnabled] = useFlashCardSetting();

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

  return (
    <CosmicBackground>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + 8 }]}>
        <View style={styles.header}>
          <Text style={styles.title}>Config</Text>
          <Text style={styles.subtitle}>
            Connexion au core, notifications, version et déconnexion.
          </Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Connexion au core</Text>

          {!editing ? (
            <>
              <View style={styles.kv}>
                <Text style={styles.kvLabel}>URL</Text>
                <Text style={styles.kvValue}>{baseUrl}</Text>
              </View>
              <View style={styles.kv}>
                <Text style={styles.kvLabel}>Clé API</Text>
                <Text style={styles.kvValue}>{maskApiKey(apiKey)}</Text>
              </View>

              <View style={styles.btnRow}>
                <Pressable
                  onPress={() => void onTestConnection()}
                  disabled={submitting}
                  style={({ pressed }) => [
                    styles.secondaryBtn,
                    { opacity: pressed || submitting ? 0.6 : 1 },
                  ]}>
                  {submitting ? (
                    <ActivityIndicator size="small" color={Cosmic.accent} />
                  ) : (
                    <Text style={styles.secondaryLabel}>Tester la connexion</Text>
                  )}
                </Pressable>
                <Pressable
                  onPress={() => {
                    setEditing(true);
                    setUpdateError(null);
                    setUpdateSuccess(null);
                  }}
                  style={({ pressed }) => [styles.primaryBtn, { opacity: pressed ? 0.7 : 1 }]}>
                  <Text style={styles.primaryLabel}>Modifier</Text>
                </Pressable>
              </View>
            </>
          ) : (
            <>
              <View style={styles.field}>
                <Text style={styles.kvLabel}>URL</Text>
                <TextInput
                  value={draftBaseUrl}
                  onChangeText={setDraftBaseUrl}
                  autoCapitalize="none"
                  autoCorrect={false}
                  keyboardType="url"
                  placeholderTextColor={Cosmic.textFaint}
                  style={styles.input}
                  editable={!submitting}
                />
              </View>
              <View style={styles.field}>
                <Text style={styles.kvLabel}>Nouvelle clé API</Text>
                <TextInput
                  value={draftApiKey}
                  onChangeText={setDraftApiKey}
                  autoCapitalize="none"
                  autoCorrect={false}
                  secureTextEntry
                  placeholder="tik_xxxxxxxxxxxx"
                  placeholderTextColor={Cosmic.textFaint}
                  style={styles.input}
                  editable={!submitting}
                />
              </View>

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
                    { opacity: pressed || submitting ? 0.6 : 1 },
                  ]}>
                  <Text style={styles.secondaryLabel}>Annuler</Text>
                </Pressable>
                <Pressable
                  onPress={() => void onSaveCredentials()}
                  disabled={submitting}
                  style={({ pressed }) => [
                    styles.primaryBtn,
                    { opacity: pressed || submitting ? 0.7 : 1 },
                  ]}>
                  {submitting ? (
                    <ActivityIndicator color={Cosmic.bgDeep} size="small" />
                  ) : (
                    <Text style={styles.primaryLabel}>Enregistrer</Text>
                  )}
                </Pressable>
              </View>
            </>
          )}

          {updateError ? (
            <Text style={styles.errorText}>{updateError}</Text>
          ) : updateSuccess ? (
            <Text style={styles.successText}>{updateSuccess}</Text>
          ) : null}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Notifications push</Text>
          <Text style={styles.muted}>
            {Platform.OS === 'web'
              ? 'Push non disponible en web. Utiliser un build natif (EAS) pour activer.'
              : 'Récupère un token Expo Push pour recevoir les alertes hors-app. Nécessite un build natif (Expo Go ne supporte plus le push remote depuis SDK 53).'}
          </Text>

          <View style={styles.kv}>
            <Text style={styles.kvLabel}>Statut</Text>
            <Text style={styles.kvValue}>{pushStatus}</Text>
          </View>
          <View style={styles.kv}>
            <Text style={styles.kvLabel}>Token</Text>
            <Text style={styles.kvValue}>{pushToken ? `${pushToken.slice(0, 24)}…` : '—'}</Text>
          </View>

          {pushReason ? <Text style={styles.muted}>{pushReason}</Text> : null}

          <Pressable
            onPress={() => void onActivatePush()}
            disabled={pushLoading || Platform.OS === 'web'}
            style={({ pressed }) => [
              styles.primaryBtn,
              { opacity: pressed || pushLoading || Platform.OS === 'web' ? 0.5 : 1 },
            ]}>
            {pushLoading ? (
              <ActivityIndicator color={Cosmic.bgDeep} size="small" />
            ) : (
              <Text style={styles.primaryLabel}>
                {pushToken ? 'Régénérer le token' : 'Activer les notifications'}
              </Text>
            )}
          </Pressable>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Affichage</Text>
          <View style={styles.toggleRow}>
            <View style={styles.toggleText}>
              <Text style={styles.toggleLabel}>Carte « Stabilité flash · BTC »</Text>
              <Text style={styles.muted}>
                Sur l&apos;onglet Marché : verdict de stabilité (instable / stable / indécis) et
                croisement carnet vs flux agressif. Aide à ne pas trader sur du bruit.
              </Text>
            </View>
            <Switch
              value={flashCardEnabled}
              onValueChange={setFlashCardEnabled}
              trackColor={{ false: Cosmic.borderStrong, true: Cosmic.accent }}
              thumbColor={Cosmic.text}
            />
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Glossaire</Text>
          <Text style={styles.muted}>
            Vocabulaire technique Tik. Tape l&apos;icône ? à côté d&apos;un terme dans l&apos;app
            pour voir sa définition rapide.
          </Text>

          <CosmicCollapsible title="Scoring du signal">
            <View style={styles.glossaryList}>
              {(['veracity', 'conviction', 'combinedBias', 'dispersion', 'seuil'] as const).map((k) => (
                <GlossaryRow key={k} entryKey={k} />
              ))}
            </View>
          </CosmicCollapsible>

          <CosmicCollapsible title="Sources et preuves">
            <View style={styles.glossaryList}>
              {(['sourceScores', 'evidence', 'triggers', 'counterScenarios'] as const).map((k) => (
                <GlossaryRow key={k} entryKey={k} />
              ))}
            </View>
          </CosmicCollapsible>

          <CosmicCollapsible title="Anti fake-news et fiabilité">
            <View style={styles.glossaryList}>
              {(['afn'] as const).map((k) => (
                <GlossaryRow key={k} entryKey={k} />
              ))}
            </View>
          </CosmicCollapsible>

          <CosmicCollapsible title="Track record et horizons">
            <View style={styles.glossaryList}>
              {(['trackRecord', 'horizon'] as const).map((k) => (
                <GlossaryRow key={k} entryKey={k} />
              ))}
            </View>
          </CosmicCollapsible>

          <CosmicCollapsible title="Workflow et discipline">
            <View style={styles.glossaryList}>
              {(['outcome', 'hypothesis', 'advisory', 'gardeFou2bis', 'shadow'] as const).map((k) => (
                <GlossaryRow key={k} entryKey={k} />
              ))}
            </View>
          </CosmicCollapsible>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>À propos</Text>
          <View style={styles.kv}>
            <Text style={styles.kvLabel}>Dashboard</Text>
            <Text style={styles.kvValue}>tik-dashboard v{APP_VERSION}</Text>
          </View>
          <View style={styles.kv}>
            <Text style={styles.kvLabel}>Core</Text>
            <Text style={styles.kvValue}>
              {healthInfo
                ? `v${healthInfo.version} · env ${healthInfo.env}`
                : healthError
                ? `Erreur : ${healthError}`
                : '—'}
            </Text>
          </View>
          <View style={styles.kv}>
            <Text style={styles.kvLabel}>Plateforme</Text>
            <Text style={styles.kvValue}>{Platform.OS}</Text>
          </View>
          <View style={styles.kv}>
            <Text style={styles.kvLabel}>Mode</Text>
            <Text style={styles.kvValue}>SHADOW (lecture seule, ADR-003)</Text>
          </View>

          <View style={styles.aboutBody}>
            <Text style={styles.aboutIntro}>
              Tik est une plateforme OSINT modulaire qui agrège des données multi-sources, score
              leur crédibilité et produit des signaux pondérés sur 3 horizons en parallèle (flash,
              swing, macro).
            </Text>

            <CosmicCollapsible title="Que fait ce dashboard ?">
              <Text style={styles.aboutText}>
                Cette application est en LECTURE SEULE. Elle se connecte au core Tik via HTTP REST et
                WebSocket pour visualiser les signaux en temps réel. Elle ne passe jamais
                d&apos;ordre ni n&apos;altère les bots Zeta/Totem (cf. ADR-003).
              </Text>
            </CosmicCollapsible>

            <CosmicCollapsible title="Architecture en 3 couches">
              <Text style={styles.aboutText}>
                • Couche 1 — Core engine (FastAPI) : source de vérité unique{'\n'}• Couche 2 — SDK
                Python (tik-sdk) : utilisé par les bots backend Zeta/Totem{'\n'}• Couche 3 —
                Dashboard Expo : ce que vous regardez (web et mobile)
              </Text>
            </CosmicCollapsible>

            <CosmicCollapsible title="Garde-fous opérationnels">
              <Text style={styles.aboutText}>
                • Mode SHADOW obligatoire (3 mois minimum) avant connexion réelle Tik ↔ Zeta{'\n'}•
                Budget de test limité à 5 % du capital pendant 1 mois après le mode shadow{'\n'}•
                Aucun bypass du guard V01-V15 côté Zeta — ADR-003
              </Text>
            </CosmicCollapsible>

            <CosmicCollapsible title="Paranoïa contrôlée">
              <Text style={styles.aboutText}>
                Chaque signal Tik livre systématiquement : une hypothèse principale, au moins 2
                contre-scénarios avec leur probabilité estimée, des preuves (evidence) avec leur
                source et leur score de crédibilité, et des triggers techniques pondérés.
              </Text>
            </CosmicCollapsible>
          </View>
        </View>

        <Pressable
          onPress={() => void signOut()}
          style={({ pressed }) => [styles.signOutBtn, { opacity: pressed ? 0.6 : 1 }]}>
          <Text style={styles.signOutLabel}>Se déconnecter</Text>
        </Pressable>
      </ScrollView>
    </CosmicBackground>
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
  title: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  subtitle: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 18,
  },
  card: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  cardTitle: {
    color: Cosmic.text,
    fontSize: 16,
    fontWeight: '700',
  },
  kv: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  kvLabel: {
    color: Cosmic.textFaint,
    fontSize: 13,
  },
  kvValue: {
    color: Cosmic.text,
    fontSize: 13,
    flexShrink: 1,
    textAlign: 'right',
    fontFamily: Fonts.mono,
  },
  field: {
    gap: 4,
  },
  input: {
    color: Cosmic.text,
    borderColor: Cosmic.borderStrong,
    backgroundColor: Cosmic.bgDeep,
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
    backgroundColor: Cosmic.accent,
  },
  primaryLabel: {
    color: Cosmic.bgDeep,
    fontWeight: '700',
  },
  secondaryBtn: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: Cosmic.borderStrong,
  },
  secondaryLabel: {
    color: Cosmic.text,
    fontWeight: '600',
  },
  errorText: {
    color: Cosmic.short,
    fontSize: 13,
  },
  successText: {
    color: Cosmic.long,
    fontSize: 13,
  },
  muted: {
    color: Cosmic.textDim,
    fontSize: 12,
    lineHeight: 18,
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  toggleText: {
    flex: 1,
    gap: 2,
  },
  toggleLabel: {
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '600',
  },
  signOutBtn: {
    marginTop: 12,
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Cosmic.short,
  },
  signOutLabel: {
    color: Cosmic.short,
    fontWeight: '700',
  },
  aboutBody: {
    marginTop: 8,
    gap: 4,
  },
  aboutIntro: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 20,
    marginBottom: 4,
  },
  aboutText: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 20,
  },
  glossaryList: {
    gap: 12,
    paddingTop: 4,
  },
  glossaryRow: {
    gap: 2,
  },
  glossaryTerm: {
    color: Cosmic.text,
    fontSize: 14,
    fontWeight: '700',
  },
  glossaryShort: {
    color: Cosmic.textDim,
    fontSize: 13,
    lineHeight: 18,
  },
  glossaryRef: {
    color: Cosmic.textFaint,
    fontSize: 11,
    fontStyle: 'italic',
  },
});
