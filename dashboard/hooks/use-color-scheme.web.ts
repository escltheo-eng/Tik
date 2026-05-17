// Variante web — comportement identique au natif depuis désactivation du
// dark mode (2026-05-17). Retourne toujours 'light'.
// Si on veut un jour réactiver le dark mode, restaurer le contenu d'origine
// qui détectait `prefers-color-scheme` via `useRNColorScheme` après
// hydratation client.
// Le type union reste `'light' | 'dark'` pour rester compatible avec
// les comparaisons éparpillées dans le code. Cf. variante native.
export function useColorScheme(): 'light' | 'dark' {
  return 'light';
}
