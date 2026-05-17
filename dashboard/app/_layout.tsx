import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { Stack, useRouter, useSegments } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import 'react-native-reanimated';

import { useColorScheme } from '@/hooks/use-color-scheme';
import { AlertsProvider } from '@/src/alerts/AlertsContext';
import { AuthProvider, useAuth } from '@/src/auth/AuthContext';
import { WatchlistProvider } from '@/src/watchlist/WatchlistContext';

export const unstable_settings = {
  anchor: '(tabs)',
};

function AuthGate() {
  const router = useRouter();
  const segments = useSegments();
  const { isAuthenticated, loading } = useAuth();

  useEffect(() => {
    if (loading) return;
    const onLogin = segments[0] === 'login';
    if (!isAuthenticated && !onLogin) {
      router.replace('/login');
    } else if (isAuthenticated && onLogin) {
      router.replace('/(tabs)');
    }
  }, [isAuthenticated, loading, segments, router]);

  return null;
}

function RootLayoutNav() {
  const colorScheme = useColorScheme();
  const { loading } = useAuth();

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      <AuthGate />
      <AlertsProvider>
        <WatchlistProvider>
          <Stack>
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="login" options={{ headerShown: false }} />
            <Stack.Screen name="signal/[id]" options={{ title: 'Détail signal' }} />
            <Stack.Screen name="modal" options={{ presentation: 'modal', title: 'Modal' }} />
          </Stack>
        </WatchlistProvider>
      </AlertsProvider>
      <StatusBar style="dark" />
    </ThemeProvider>
  );
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <RootLayoutNav />
    </AuthProvider>
  );
}

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
