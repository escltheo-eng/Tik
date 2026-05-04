import { useEffect, useState } from 'react';

/**
 * Force un re-render périodique du composant et retourne le compteur courant.
 *
 * Usage typique : rafraîchir un affichage calculé à partir de l'horloge
 * courante (ex: `timeAgo(timestamp)`) sans dépendre de l'arrivée d'un
 * nouvel évènement externe (WS, refetch HTTP, …).
 *
 * Le retour est utile pour les composants mémoïsés type `FlatList` :
 * passer la valeur via `extraData={tick}` invalide le cache des rows et
 * force leur recomputation. Pour les vues simples (ScrollView, .map()),
 * la valeur peut être ignorée — appeler `useTick()` seul suffit.
 *
 * @param intervalMs intervalle en millisecondes (défaut 30 000 = 30 s).
 */
export function useTick(intervalMs: number = 30_000): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return tick;
}
