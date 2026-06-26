/**
 * UnavailableState — composant PARTAGÉ « Contrat des 4 états » (CLAUDE.md §13ter).
 *
 * Affiche de façon COHÉRENTE et HONNÊTE l'absence de donnée, en distinguant 4
 * états jamais confondus (+ un 5ᵉ by-design) :
 *  - 'loading'  : chargement en cours
 *  - 'error'    : panne → message FR métier via humanizeError (JAMAIS un dump technique)
 *  - 'empty'    : pas de donnée + sa CAUSE (message explicite passé par la carte)
 *  - 'disabled' : état VOLONTAIRE / by-design (source désactivée, shadow…) → pédagogique
 *
 * But : un seul composant → des dizaines de cartes cohérentes d'un coup. On ne
 * peut plus confondre « vide » et « panne », ni afficher « 401 Forbidden {…} » brut.
 * Anti vernis (Axe #1) : on clarifie l'absence, on ne la maquille pas.
 */
import { StyleSheet, Text, View } from 'react-native';

import { Cosmic } from '@/constants/cosmic';
import { humanizeError } from '@/src/utils/humanize-error';

export type UnavailableKind = 'loading' | 'error' | 'empty' | 'disabled';

export interface UnavailableStateProps {
  kind: UnavailableKind;
  /** kind='error' : l'erreur brute (objet Error ou string) → traduite en FR. */
  error?: unknown;
  /** kind='empty'/'disabled'/'loading' : la cause/explication affichée telle quelle. */
  message?: string;
}

export function UnavailableState({ kind, error, message }: UnavailableStateProps) {
  let text: string;
  let color: string;
  let icon = '';

  switch (kind) {
    case 'loading':
      text = message ?? 'Chargement…';
      color = Cosmic.textFaint;
      break;
    case 'error':
      text = message ?? humanizeError(error);
      color = Cosmic.short; // rouge doux — c'est une panne, pas un vide
      icon = '⚠ ';
      break;
    case 'disabled':
      text = message ?? 'Indisponible (volontaire).';
      color = Cosmic.textFaint;
      icon = '✋ ';
      break;
    case 'empty':
    default:
      text = message ?? 'Aucune donnée pour le moment.';
      color = Cosmic.textFaint;
      break;
  }

  return (
    <View style={styles.wrap}>
      <Text style={[styles.text, { color }]}>
        {icon}
        {text}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingVertical: 10 },
  text: { fontSize: 13, lineHeight: 18 },
});
