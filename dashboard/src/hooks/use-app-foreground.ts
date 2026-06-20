import { useEffect, useRef } from 'react';
import { AppState, type AppStateStatus } from 'react-native';

/**
 * Appelle `onForeground` quand l'app revient au PREMIER PLAN (AppState 'active'
 * après un passage en arrière-plan / écran éteint).
 *
 * Pourquoi : quand Expo Go n'est plus au premier plan, l'OS **suspend les
 * minuteries JS** (`setInterval` gelé) et les WebSockets. Au retour, rien ne se
 * rafraîchit avant le prochain tick (jusqu'à plusieurs minutes selon le hook) →
 * l'utilisatrice a l'impression de devoir « recharger la page ». Ce hook permet
 * à chaque ressource (poll HTTP, horloge) de se rafraîchir IMMÉDIATEMENT au
 * retour, sans reload manuel.
 *
 * Ne déclenche que sur une vraie transition non-active → active (on ignore les
 * flickers 'inactive' brefs type centre de notifications). Le callback est gardé
 * dans un ref → l'abonnement AppState n'est créé qu'UNE fois, même si
 * `onForeground` change d'identité à chaque render.
 */
export function useAppForeground(onForeground: () => void): void {
  const cbRef = useRef(onForeground);
  cbRef.current = onForeground;

  useEffect(() => {
    let last: AppStateStatus = AppState.currentState;
    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (next === 'active' && last !== 'active') {
        cbRef.current();
      }
      last = next;
    });
    return () => sub.remove();
  }, []);
}
