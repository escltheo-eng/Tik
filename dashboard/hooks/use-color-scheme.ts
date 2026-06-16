/**
 * App forcée en thème SOMBRE (refonte cosmique γ, bout 5).
 *
 * L'identité visuelle Tik est sombre uniquement : on ignore volontairement le
 * réglage clair/sombre de l'appareil pour garder une seule esthétique cohérente
 * sur tous les écrans (les écrans encore « thémés » via ThemedView/ThemedText
 * adoptent ainsi la palette cosmique de `Colors.dark`). Réversible : remettre
 * `export { useColorScheme } from 'react-native';` rétablit le suivi système.
 */
export function useColorScheme(): 'light' | 'dark' {
  return 'dark';
}
