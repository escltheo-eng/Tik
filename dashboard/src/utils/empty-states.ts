/**
 * Messages d'état vide de la liste Signals — Contrat des 4 états, état 5 ✋.
 *
 * Découvert le 2026-07-02 (captures trader) : « BTC + Macro » affichait
 * « Aucun signal pour l'instant. Le flux est ouvert, les nouveaux signaux
 * apparaîtront ici » — message MALHONNÊTE pour un horizon qu'aucun moteur ne
 * produit (le moteur macro semaines-mois n'existe pas, backlog). Idem
 * « GOLD + Micro » (labo ML = BTC uniquement, whitelist ADR-034).
 * MAJ 2026-07-03 : le flash GOLD existe désormais via le proxy PAXG (ADR-040,
 * shadow) — le message « pas de flash GOLD par design (ADR-005) » est périmé.
 *
 * Fonction pure — testée dans __tests__/empty-states.test.ts.
 */

export function emptyStateMessage(
  entity: string | undefined,
  horizon: string | undefined,
): string {
  if (horizon === 'macro') {
    return (
      "✋ Le moteur macro (semaines-mois) n'existe pas encore — il est au backlog. " +
      "Aucun signal n'apparaîtra sur cet horizon tant qu'il n'est pas construit."
    );
  }
  if (entity === 'GOLD' && horizon === 'flash') {
    return (
      'Pas de signal flash GOLD dans la fenêtre. Le flash GOLD (proxy PAXG, ' +
      'ADR-040, shadow) est en pause quand le marché de l’or est fermé ' +
      '(ven 21h → dim 22h UTC) et n’émet qu’aux transitions de direction.'
    );
  }
  if (entity === 'GOLD' && horizon === 'micro') {
    return '✋ Le micro (labo ML, mesure shadow) ne couvre que BTC — pas de micro GOLD.';
  }
  return 'Aucun signal pour l’instant. Le flux est ouvert, les nouveaux signaux apparaîtront ici.';
}
