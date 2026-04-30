import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  TextInput,
} from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Fonts, Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { HttpClient } from '@/src/api/client';
import { getHealth, listEntities } from '@/src/api/endpoints';
import { AuthError, NetworkError, TikError } from '@/src/api/errors';
import { useAuth } from '@/src/auth/AuthContext';
import { DEFAULT_BASE_URL } from '@/src/auth/storage';

export default function LoginScreen() {
  const { signIn, baseUrl: currentBaseUrl } = useAuth();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];

  const [baseUrl, setBaseUrl] = useState<string>(currentBaseUrl || DEFAULT_BASE_URL);
  const [apiKey, setApiKey] = useState<string>('');
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const onSubmit = async () => {
    if (!baseUrl.trim()) {
      setErrorMessage('L’URL du core est requise.');
      return;
    }
    if (!apiKey.trim()) {
      setErrorMessage('La clé API est requise.');
      return;
    }
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const probe = new HttpClient({ baseUrl: baseUrl.trim(), apiKey: apiKey.trim() });
      // 1. /health : vérifie la connectivité au core (public, rapide).
      await getHealth(probe);
      // 2. /entities : vérifie que la clé API est bien valide (endpoint authentifié).
      await listEntities(probe);
      await signIn(baseUrl.trim(), apiKey.trim());
    } catch (err) {
      let msg: string;
      if (err instanceof AuthError) {
        msg = 'Clé API refusée par le core (401/403). Vérifie qu’elle est valide et active.';
      } else if (err instanceof NetworkError) {
        msg = `Core injoignable à cette URL : ${err.message}`;
      } else if (err instanceof TikError) {
        msg = err.message;
      } else {
        msg = (err as Error).message;
      }
      setErrorMessage(msg);
    } finally {
      setSubmitting(false);
    }
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
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.flex}>
      <ThemedView style={styles.container}>
        <ThemedView style={styles.header}>
          <ThemedText
            style={[styles.brand, { fontFamily: Fonts.rounded, color: palette.tint }]}>
            Tik
          </ThemedText>
          <ThemedText type="title">Connexion au core</ThemedText>
          <ThemedText style={styles.muted}>
            Renseigne l’URL du core Tik et ta clé API. La clé est stockée localement
            (Keychain sur iOS, EncryptedSharedPreferences sur Android, localStorage sur web).
          </ThemedText>
        </ThemedView>

        <ThemedView style={styles.field}>
          <ThemedText type="defaultSemiBold">URL du core</ThemedText>
          <TextInput
            value={baseUrl}
            onChangeText={setBaseUrl}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            placeholder="http://localhost:8200"
            placeholderTextColor={palette.icon}
            style={inputStyle}
            editable={!submitting}
          />
          <ThemedText style={styles.help}>
            En développement local, garde la valeur par défaut.
          </ThemedText>
        </ThemedView>

        <ThemedView style={styles.field}>
          <ThemedText type="defaultSemiBold">Clé API</ThemedText>
          <TextInput
            value={apiKey}
            onChangeText={setApiKey}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
            placeholder="tik_xxxxxxxxxxxx"
            placeholderTextColor={palette.icon}
            style={inputStyle}
            editable={!submitting}
          />
          <ThemedText style={styles.help}>
            Générer via : python -m tik_core.scripts.create_api_key
          </ThemedText>
        </ThemedView>

        {errorMessage ? (
          <ThemedView style={styles.errorBox}>
            <ThemedText style={{ color: '#c0392b' }}>{errorMessage}</ThemedText>
          </ThemedView>
        ) : null}

        <Pressable
          onPress={onSubmit}
          disabled={submitting}
          style={({ pressed }) => [
            styles.submit,
            { backgroundColor: Colors.light.tint, opacity: pressed || submitting ? 0.7 : 1 },
          ]}>
          {submitting ? (
            <ActivityIndicator color="#ffffff" />
          ) : (
            <ThemedText style={styles.submitLabel}>Se connecter</ThemedText>
          )}
        </Pressable>

        <ThemedText style={styles.footer}>
          Lecture seule — ADR-003. Aucune exécution d’ordre n’est possible.
        </ThemedText>
      </ThemedView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
  },
  container: {
    flex: 1,
    padding: 24,
    paddingTop: 80,
    gap: 16,
  },
  header: {
    gap: 8,
    marginBottom: 16,
  },
  brand: {
    fontSize: 64,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  muted: {
    opacity: 0.7,
    fontSize: 14,
    lineHeight: 20,
  },
  field: {
    gap: 6,
  },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
  },
  help: {
    fontSize: 12,
    opacity: 0.6,
  },
  errorBox: {
    borderWidth: 1,
    borderColor: '#c0392b',
    borderRadius: 8,
    padding: 12,
    backgroundColor: 'rgba(192, 57, 43, 0.08)',
  },
  submit: {
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 8,
  },
  submitLabel: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  footer: {
    fontSize: 12,
    opacity: 0.5,
    textAlign: 'center',
    marginTop: 24,
  },
});
