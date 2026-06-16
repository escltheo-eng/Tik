/**
 * App forcée en thème SOMBRE (refonte cosmique γ, bout 5) — variante web.
 * Même choix que `use-color-scheme.ts` : esthétique sombre unique, on ignore le
 * réglage système. Réversible (restaurer la version basée sur useRNColorScheme).
 */
export function useColorScheme(): 'light' | 'dark' {
  return 'dark';
}
