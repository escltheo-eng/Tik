/**
 * Réglage local « afficher la carte Stabilité flash » (onglet Marché).
 *
 * Petit store partagé (Marché lit, Config écrit) backé par AsyncStorage +
 * notification des abonnés pour une mise à jour live entre onglets. Défaut :
 * visible (true). Entièrement réversible : supprimer ce fichier + ses 2
 * usages (carte Marché, interrupteur Config) restaure l'UX d'origine.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';

const STORAGE_KEY = 'tik.settings.flashStabilityCard';

type Listener = (value: boolean) => void;

let current = true; // défaut : carte visible
let hydrated = false;
const listeners = new Set<Listener>();

function notify(): void {
  for (const l of listeners) l(current);
}

async function hydrate(): Promise<void> {
  if (hydrated) return;
  hydrated = true;
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw !== null) {
      current = raw === '1';
      notify();
    }
  } catch (err) {
    console.warn('[flashCardSetting] hydrate failed (best-effort)', err);
  }
}

export async function setFlashCardEnabled(value: boolean): Promise<void> {
  current = value;
  notify();
  try {
    await AsyncStorage.setItem(STORAGE_KEY, value ? '1' : '0');
  } catch (err) {
    console.warn('[flashCardSetting] persist failed (best-effort)', err);
  }
}

/** Hook partagé : retourne [enabled, setter]. */
export function useFlashCardSetting(): [boolean, (value: boolean) => void] {
  const [enabled, setEnabled] = useState(current);

  useEffect(() => {
    const listener: Listener = (v) => setEnabled(v);
    listeners.add(listener);
    setEnabled(current);
    void hydrate();
    return () => {
      listeners.delete(listener);
    };
  }, []);

  return [enabled, (v: boolean) => void setFlashCardEnabled(v)];
}
