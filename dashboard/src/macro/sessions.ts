/**
 * Séances de marché (forex / or) — logique PURE, déterministe, sans I/O ni `Intl`.
 *
 * Donne, pour un instant `now` donné, l'état des quatre grandes séances
 * (Océanie/Sydney · Asie/Tokyo · Europe/Londres · US/New York), du chevauchement
 * Londres–NY (fenêtre la plus liquide), du « creux quotidien » NY→Sydney, et de
 * l'état du marché de l'or (COMEX, jours fériés inclus) + BTC.
 *
 * ⚠️ CONTEXTE / DISCIPLINE, PAS un signal : ceci dit QUAND le marché est
 * ouvert / liquide, JAMAIS dans quel sens il va (Axe #1, NO-GO directionnel).
 *
 * Heures de séance (UTC), conventions de place (vérifiées 2026-06) :
 *   - Sydney  : 22:00–07:00 UTC (hiver austral/AEST) · 21:00–06:00 UTC (été austral/AEDT).
 *   - Tokyo   : 00:00–09:00 UTC (le Japon n'observe pas l'heure d'été).
 *   - Londres : 07:00–16:00 UTC (été/BST) · 08:00–17:00 UTC (hiver/GMT).
 *   - New York: 12:00–21:00 UTC (été/EDT) · 13:00–22:00 UTC (hiver/EST).
 *   - Or COMEX électronique : ~23 h/5, pause quotidienne ~1 h (17h–18h ET),
 *     fermé le week-end ET les jours fériés US (liste passée en paramètre).
 *
 * Sydney ouvre la journée de trading : sans elle, l'intervalle ~22:00→00:00 UTC
 * paraît « tout fermé » alors que l'Asie-Pacifique est active. Reste un vrai creux
 * ~21:00–22:00 UTC (clôture NY avant l'ouverture de Sydney = pause COMEX l'été).
 *
 * Heure d'été calculée par les RÈGLES officielles, donc aucune dépendance à
 * `Intl`/`zoneinfo` : UE (dernier dim. mars→octobre), US (2e dim. mars→1er dim.
 * novembre), Australie INVERSÉE (1er dim. octobre→1er dim. avril). Londres/NY/Sydney
 * basculent à des dates différentes : le chevauchement et le creux sont recalculés
 * dynamiquement (donc justes même pendant les semaines de décalage).
 */

export type MarketState = 'open' | 'closed';
export type GoldState = 'open' | 'pause' | 'closed';

export interface SessionRow {
  id: 'oceania' | 'asia' | 'europe' | 'us';
  label: string;
  hoursUtc: string; // "22:00–07:00 UTC"
  state: MarketState;
}

export interface SessionsSnapshot {
  utcLabel: string; // "14:32 UTC"
  weekend: boolean;
  dailyLull: boolean; // jour de semaine où aucune des 4 séances n'est ouverte (creux NY→Sydney)
  sessions: SessionRow[];
  overlapActive: boolean;
  overlapHoursUtc: string; // "12:00–16:00 UTC"
  gold: { state: GoldState; note: string };
  btcNote: string;
}

// --- Helpers heure d'été (dimanches calculés en UTC) ---

function nthSundayOfMonth(year: number, month0: number, n: number): number {
  const firstDow = new Date(Date.UTC(year, month0, 1)).getUTCDay(); // 0 = dimanche
  const firstSunday = 1 + ((7 - firstDow) % 7);
  return firstSunday + (n - 1) * 7;
}

function lastSundayOfMonth(year: number, month0: number): number {
  const lastDay = new Date(Date.UTC(year, month0 + 1, 0)).getUTCDate();
  const lastDow = new Date(Date.UTC(year, month0, lastDay)).getUTCDay();
  return lastDay - lastDow;
}

export function isEuSummerTime(now: Date): boolean {
  const y = now.getUTCFullYear();
  const start = Date.UTC(y, 2, lastSundayOfMonth(y, 2), 1); // dernier dim. mars 01:00 UTC
  const end = Date.UTC(y, 9, lastSundayOfMonth(y, 9), 1); // dernier dim. oct. 01:00 UTC
  const t = now.getTime();
  return t >= start && t < end;
}

export function isUsSummerTime(now: Date): boolean {
  const y = now.getUTCFullYear();
  const start = Date.UTC(y, 2, nthSundayOfMonth(y, 2, 2), 7); // 2e dim. mars 07:00 UTC
  const end = Date.UTC(y, 10, nthSundayOfMonth(y, 10, 1), 6); // 1er dim. nov. 06:00 UTC
  const t = now.getTime();
  return t >= start && t < end;
}

/** Heure d'été australienne (AEDT, hémisphère sud INVERSÉ : oct.→avr.). */
export function isAuSummerTime(now: Date): boolean {
  const y = now.getUTCFullYear();
  const t = now.getTime();
  const octStart = Date.UTC(y, 9, nthSundayOfMonth(y, 9, 1), 16); // 1er dim. oct. (~02:00 AEDT)
  const aprEnd = Date.UTC(y, 3, nthSundayOfMonth(y, 3, 1), 16); // 1er dim. avr. (~03:00 AEDT)
  return t >= octStart || t < aprEnd;
}

// --- Formatage ---

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function windowLabel(open: number, close: number): string {
  return `${pad2(open)}:00–${pad2(close)}:00 UTC`;
}

// --- Or COMEX ---

function computeGold(
  day: number,
  hour: number,
  usSummer: boolean,
  goldHolidayName: string | null,
): { state: GoldState; note: string } {
  // Jour férié US : COMEX fermé toute la journée.
  if (goldHolidayName) {
    return { state: 'closed', note: `fermé (férié US — ${goldHolidayName})` };
  }
  const pauseStart = usSummer ? 21 : 22; // 17:00 ET
  const pauseEnd = usSummer ? 22 : 23; // 18:00 ET
  const closed =
    day === 6 || // samedi
    (day === 5 && hour >= pauseStart) || // vendredi après la clôture
    (day === 0 && hour < pauseEnd); // dimanche avant la réouverture
  if (closed) {
    return { state: 'closed', note: 'fermé (week-end)' };
  }
  if (hour >= pauseStart && hour < pauseEnd) {
    return { state: 'pause', note: 'pause quotidienne COMEX (~1 h)' };
  }
  return { state: 'open', note: 'marché ouvert' };
}

// --- Snapshot principal ---

/**
 * @param now              instant courant
 * @param goldHolidayName  nom du jour férié US si `now` en est un, sinon null
 *                         (fourni par `usMarketHolidayName` côté composant — garde
 *                          ce module pur et testable en isolation).
 */
export function computeSessions(now: Date, goldHolidayName: string | null = null): SessionsSnapshot {
  const day = now.getUTCDay(); // 0 = dimanche … 6 = samedi
  const hour = now.getUTCHours() + now.getUTCMinutes() / 60;
  const euSummer = isEuSummerTime(now);
  const usSummer = isUsSummerTime(now);
  const auSummer = isAuSummerTime(now);

  const sydneyOpen = auSummer ? 21 : 22;
  const sydneyClose = auSummer ? 6 : 7;
  const londonOpen = euSummer ? 7 : 8;
  const londonClose = euSummer ? 16 : 17;
  const nyOpen = usSummer ? 12 : 13;
  const nyClose = usSummer ? 21 : 22;

  // Week-end forex : samedi entier ; vendredi après la clôture NY ; dimanche
  // avant la réouverture de Sydney (= ouverture réelle de la semaine forex).
  const weekend =
    day === 6 || (day === 5 && hour >= nyClose) || (day === 0 && hour < sydneyOpen);

  // Séances « normales » (ne franchissent pas minuit).
  const inWindow = (open: number, close: number): boolean =>
    !weekend && hour >= open && hour < close;
  // Sydney franchit minuit (ouvre le soir, ferme le lendemain matin).
  const inWrapWindow = (open: number, close: number): boolean =>
    !weekend && (hour >= open || hour < close);

  const sessions: SessionRow[] = [
    {
      id: 'oceania',
      label: 'Océanie (Sydney)',
      hoursUtc: windowLabel(sydneyOpen, sydneyClose),
      state: inWrapWindow(sydneyOpen, sydneyClose) ? 'open' : 'closed',
    },
    {
      id: 'asia',
      label: 'Asie (Tokyo)',
      hoursUtc: windowLabel(0, 9),
      state: inWindow(0, 9) ? 'open' : 'closed',
    },
    {
      id: 'europe',
      label: 'Europe (Londres)',
      hoursUtc: windowLabel(londonOpen, londonClose),
      state: inWindow(londonOpen, londonClose) ? 'open' : 'closed',
    },
    {
      id: 'us',
      label: 'US (New York)',
      hoursUtc: windowLabel(nyOpen, nyClose),
      state: inWindow(nyOpen, nyClose) ? 'open' : 'closed',
    },
  ];

  const overlapStart = Math.max(londonOpen, nyOpen);
  const overlapEnd = Math.min(londonClose, nyClose);
  const overlapActive = !weekend && hour >= overlapStart && hour < overlapEnd;

  // Creux quotidien : en semaine, aucune séance ouverte (clôture NY avant Sydney).
  const dailyLull = !weekend && sessions.every((s) => s.state === 'closed');

  return {
    utcLabel: `${pad2(now.getUTCHours())}:${pad2(now.getUTCMinutes())} UTC`,
    weekend,
    dailyLull,
    sessions,
    overlapActive,
    overlapHoursUtc: windowLabel(overlapStart, overlapEnd),
    gold: computeGold(day, hour, usSummer, goldHolidayName),
    btcNote: '24/7 — jamais fermé. La liquidité culmine pendant le chevauchement Londres–NY.',
  };
}
