// Le mode sombre a été désactivé sur demande utilisatrice (2026-05-17).
// `app.json` force `userInterfaceStyle: "light"` côté Expo natif, mais on
// court-circuite aussi le hook au cas où un consommateur appellerait
// `useColorScheme` directement (sans passer par la config Expo) — par
// exemple un test, un dev tool, ou Expo Go avant rebuild du dev client.
// Si on veut un jour réactiver le dark mode, il suffira de remplacer
// par : `export { useColorScheme } from 'react-native';`
// Le type union reste `'light' | 'dark'` pour ne pas casser les
// comparaisons `colorScheme === 'dark'` éparpillées dans le code
// (chemins inactifs aujourd'hui, prêts à se réactiver si on rétablit
// le dark mode plus tard).
export function useColorScheme(): 'light' | 'dark' {
  return 'light';
}
