import { Tabs } from 'expo-router';
import React from 'react';

import { HapticTab } from '@/components/haptic-tab';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useAlerts } from '@/src/alerts/AlertsContext';

export default function TabLayout() {
  const colorScheme = useColorScheme();
  const { unreadCount } = useAlerts();

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: Colors[colorScheme ?? 'light'].tint,
        headerShown: false,
        tabBarButton: HapticTab,
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Home',
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
        name="watchlist"
        options={{
          title: 'Watchlist',
          tabBarIcon: ({ color }) => <IconSymbol size={28} name="star.fill" color={color} />,
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
        name="alerts"
        options={{
          title: 'Alerts',
          tabBarIcon: ({ color }) => <IconSymbol size={28} name="bell.fill" color={color} />,
          tabBarBadge: unreadCount > 0 ? String(unreadCount) : undefined,
        }}
      />
      <Tabs.Screen
        name="bots"
        options={{
          href: null,
        }}
      />
      <Tabs.Screen
        name="config"
        options={{
          title: 'Config',
          tabBarIcon: ({ color }) => <IconSymbol size={28} name="gearshape.fill" color={color} />,
        }}
      />
      <Tabs.Screen
        name="about"
        options={{
          href: null,
        }}
      />
    </Tabs>
  );
}
