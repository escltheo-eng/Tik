/**
 * Paramètres brokers du comparateur de coûts (en points).
 *
 * ⚠️⚠️ CHIFFRES À VÉRIFIER — CE SONT DES EXEMPLES, PAS LES VRAIS TARIFS ⚠️⚠️
 *
 * Les valeurs ci-dessous servent uniquement à faire tourner le calcul. Elles
 * NE sont PAS relevées chez Pepperstone ni ActivTrades. Remplace-les par TES
 * chiffres réels (grille tarifaire de ton type de compte, ou relevé observé
 * en direct dans la plateforme), puis passe `verified: true` pour le broker.
 *
 * Tant que `verified: false`, la carte affiche un badge « à vérifier » pour
 * éviter de te faire confiance à un chiffre inventé sur de l'argent réel.
 *
 * ── Définition d'un « point » ───────────────────────────────────────────
 * Un point = plus petit incrément de prix coté par le broker pour
 * l'instrument. GARDE LA MÊME DÉFINITION entre les deux brokers, sinon la
 * comparaison n'a pas de sens. Conventions courantes (à confirmer chez toi) :
 *   BTC/USD  → 1 point = 1.00 $
 *   XAU/USD  → 1 point = 0.01 $   (1 pip = 0.10 $)
 *
 * ── Champs ──────────────────────────────────────────────────────────────
 * - spreadPoints           : spread typique (points)
 * - commissionPoints       : commission aller-retour convertie en points
 *                            (0 si compte « spread only »)
 * - swapPointsLong/Short   : financement overnight par nuit (points ;
 *                            négatif = coût, positif = crédit)
 * - maxLeverage            : levier max (contrainte de marge, pas un gain)
 *
 * La fiscalité (impôt sur les gains) n'apparaît PAS ici : elle est identique
 * quel que soit le broker en France → elle ne départage pas le choix.
 */

import type { BrokerSpec } from './calc';

export const BROKER_SPECS: BrokerSpec[] = [
  {
    id: 'pepperstone',
    name: 'Pepperstone',
    maxLeverage: 500, // EXEMPLE — vérifie selon ton compte/instrument
    verified: false,
    perInstrument: {
      // EXEMPLES à remplacer par tes chiffres réels :
      BTC: {
        spreadPoints: 30,
        commissionPoints: 0,
        swapPointsLongPerNight: -8,
        swapPointsShortPerNight: -8,
      },
      GOLD: {
        spreadPoints: 12,
        commissionPoints: 0,
        swapPointsLongPerNight: -2,
        swapPointsShortPerNight: -1,
      },
    },
  },
  {
    id: 'activtrades',
    name: 'ActivTrades',
    maxLeverage: 1000, // EXEMPLE — vérifie selon ton compte/instrument
    verified: false,
    perInstrument: {
      // EXEMPLES à remplacer par tes chiffres réels :
      BTC: {
        spreadPoints: 40,
        commissionPoints: 0,
        swapPointsLongPerNight: -10,
        swapPointsShortPerNight: -9,
      },
      GOLD: {
        spreadPoints: 15,
        commissionPoints: 0,
        swapPointsLongPerNight: -2,
        swapPointsShortPerNight: -1,
      },
    },
  },
];
