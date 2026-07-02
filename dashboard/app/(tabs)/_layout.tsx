import { Tabs } from 'expo-router';
import React from 'react';

import { HapticTab } from '@/components/haptic-tab';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { Cosmic } from '@/constants/cosmic';
import { useAlerts } from '@/src/alerts/AlertsContext';

export default function TabLayout() {
  const { unreadCount } = useAlerts();

  return (
    <Tabs
      screenOptions={{
        // Barre d'onglets cosmique (refonte γ, bout 6) — 5 onglets, sombre, accent ambre.
        tabBarActiveTintColor: Cosmic.accent,
        tabBarInactiveTintColor: Cosmic.textFaint,
        headerShown: false,
        tabBarButton: HapticTab,
        tabBarStyle: {
          backgroundColor: Cosmic.bgDeep,
          borderTopColor: Cosmic.border,
        },
      }}>
      {/* --- 5 onglets visibles : Cockpit · Signals · Sources · Carnet · Plus --- */}
      <Tabs.Screen
        name="index"
        options={{
          title: 'Cockpit',
          tabBarIcon: ({ color }) => <IconSymbol size={28} name="house.fill" color={color} />,
        }}
      />
      <Tabs.Screen
        name="signals"
        options={{
          title: 'Signals',
          tabBarIcon: ({ color }) => (
            <IconSymbol size={28} name="chart.line.uptrend.xyaxis" color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="sources"
        options={{
          title: 'Sources',
          tabBarIcon: ({ color }) => <IconSymbol size={28} name="globe" color={color} />,
        }}
      />
      <Tabs.Screen
        name="journal"
        options={{
          title: 'Carnet',
          tabBarIcon: ({ color }) => <IconSymbol size={28} name="book.fill" color={color} />,
        }}
      />
      <Tabs.Screen
        name="plus"
        options={{
          title: 'Plus',
          tabBarIcon: ({ color }) => (
            <IconSymbol size={28} name="person.crop.circle.fill" color={color} />
          ),
          // Le badge alertes non-lues remonte ici (Alerts vit dans le hub Plus).
          tabBarBadge: unreadCount > 0 ? String(unreadCount) : undefined,
        }}
      />

      {/* --- Écrans hors barre du bas (accessibles depuis le hub Plus) --- */}
      <Tabs.Screen name="watchlist" options={{ href: null }} />
      <Tabs.Screen name="alerts" options={{ href: null }} />
      <Tabs.Screen name="config" options={{ href: null }} />
      <Tabs.Screen name="bots" options={{ href: null }} />
      <Tabs.Screen name="about" options={{ href: null }} />
    </Tabs>
  );
}
