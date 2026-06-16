/**
 * Écran Carnet de trades manuels (Levier B 2026-06-03) — version cosmique (bout 6).
 *
 * Journal des vrais trades de la trader : ouverture (avec snapshot du contexte
 * Tik à l'entrée), liste ouverts/clôturés, clôture (→ résultat %), bilan
 * « Tik t'a-t-il aidée ? ». Stockage serveur (VPS) via /api/v1/trades.
 *
 * Reskin cosmique : toute la logique est conservée à l'identique ; seul le rendu
 * passe en palette γ (fond sombre, champs sombres, boutons ambre à texte foncé).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { CosmicBackground } from '@/components/cosmic/cosmic-background';
import { JournalStatsCard } from '@/components/journal/journal-stats-card';
import { Cosmic, TitleShadow, serifTitleFamily } from '@/constants/cosmic';
import { getLatestSignals } from '@/src/api/endpoints';
import type { ManualTrade } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { useTrades } from '@/src/journal/useTrades';
import { timeAgo } from '@/src/utils/time';

type Entity = 'BTC' | 'GOLD';
type Direction = 'long' | 'short';

const PLACEHOLDER = '#5b6b8c';

function directionColor(direction: string): string {
  if (direction === 'long') return Cosmic.long;
  if (direction === 'short') return Cosmic.short;
  return Cosmic.neutral;
}

interface TikSnapshot {
  signalId: string | null;
  direction: 'long' | 'short' | 'neutral' | null;
  veracity: number | null;
}

function alignmentPreview(dir: Direction, tik: TikSnapshot | null): string {
  const t = tik?.direction;
  if (t !== 'long' && t !== 'short') return 'sans signal directionnel';
  return dir === t ? 'avec Tik' : 'contre Tik';
}

function alignmentLabel(a: string | null): { text: string; color: string } {
  switch (a) {
    case 'with':
      return { text: 'avec Tik', color: Cosmic.long };
    case 'against':
      return { text: 'contre Tik', color: Cosmic.short };
    default:
      return { text: 'sans signal', color: Cosmic.textFaint };
  }
}

export default function JournalScreen() {
  const insets = useSafeAreaInsets();
  const { client, isAuthenticated } = useAuth();
  const { trades, stats, loading, error, refresh, open, close, remove } = useTrades();

  // --- Formulaire d'ouverture ---
  const [showForm, setShowForm] = useState(false);
  const [entity, setEntity] = useState<Entity>('BTC');
  const [direction, setDirection] = useState<Direction>('short');
  const [entryPrice, setEntryPrice] = useState('');
  const [sizeLots, setSizeLots] = useState('');
  const [stopPrice, setStopPrice] = useState('');
  const [targetPrice, setTargetPrice] = useState('');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [tik, setTik] = useState<TikSnapshot | null>(null);

  // Snapshot Tik : dernier signal swing de l'entity sélectionnée.
  useEffect(() => {
    if (!showForm || !isAuthenticated) return;
    let cancelled = false;
    getLatestSignals(client, { entity, horizon: 'swing', limit: 1 })
      .then((sigs) => {
        if (cancelled) return;
        const s = sigs[0];
        if (!s) {
          setTik(null);
          return;
        }
        const d = s.direction;
        setTik({
          signalId: s.id,
          direction: d === 'long' || d === 'short' || d === 'neutral' ? d : null,
          veracity: s.veracity ?? null,
        });
      })
      .catch(() => {
        if (!cancelled) setTik(null);
      });
    return () => {
      cancelled = true;
    };
  }, [client, isAuthenticated, showForm, entity]);

  const resetForm = useCallback(() => {
    setEntryPrice('');
    setSizeLots('');
    setStopPrice('');
    setTargetPrice('');
    setNote('');
  }, []);

  const submit = useCallback(async () => {
    const ep = parseFloat(entryPrice.replace(',', '.'));
    const sl = parseFloat(sizeLots.replace(',', '.'));
    if (!Number.isFinite(ep) || ep <= 0) {
      Alert.alert('Prix d’entrée manquant', 'Saisis un prix d’entrée valide (> 0).');
      return;
    }
    if (!Number.isFinite(sl) || sl <= 0) {
      Alert.alert('Taille manquante', 'Saisis une taille en lots MT5 valide (> 0).');
      return;
    }
    const sp = parseFloat(stopPrice.replace(',', '.'));
    const tp = parseFloat(targetPrice.replace(',', '.'));
    setSubmitting(true);
    try {
      await open({
        entity_id: entity,
        direction,
        entry_price: ep,
        size_lots: sl,
        stop_price: Number.isFinite(sp) && sp > 0 ? sp : null,
        target_price: Number.isFinite(tp) && tp > 0 ? tp : null,
        note: note.trim() ? note.trim() : null,
        tik_signal_id: tik?.signalId ?? null,
        tik_direction: tik?.direction ?? null,
        tik_veracity: tik?.veracity ?? null,
      });
      resetForm();
      setShowForm(false);
    } catch (err) {
      Alert.alert('Échec de l’enregistrement', (err as Error).message ?? 'erreur');
    } finally {
      setSubmitting(false);
    }
  }, [entity, direction, entryPrice, sizeLots, stopPrice, targetPrice, note, tik, open, resetForm]);

  const onClose = useCallback(
    (trade: ManualTrade) => {
      // Alert.prompt = iOS uniquement (cible = iPhone). Saisie du prix de sortie.
      Alert.prompt(
        'Clôturer le trade',
        `${trade.entity_id} ${trade.direction.toUpperCase()} entré à ${trade.entry_price}\nPrix de sortie :`,
        [
          { text: 'Annuler', style: 'cancel' },
          {
            text: 'Clôturer',
            onPress: (value?: string) => {
              const xp = parseFloat((value ?? '').replace(',', '.'));
              if (!Number.isFinite(xp) || xp <= 0) {
                Alert.alert('Prix invalide', 'Saisis un prix de sortie valide (> 0).');
                return;
              }
              close(trade.id, { exit_price: xp }).catch((err) =>
                Alert.alert('Échec', (err as Error).message ?? 'erreur'),
              );
            },
          },
        ],
        'plain-text',
        '',
        'decimal-pad',
      );
    },
    [close],
  );

  const onDelete = useCallback(
    (trade: ManualTrade) => {
      Alert.alert(
        'Supprimer ce trade ?',
        `${trade.entity_id} ${trade.direction.toUpperCase()} · ${trade.entry_price}`,
        [
          { text: 'Annuler', style: 'cancel' },
          {
            text: 'Supprimer',
            style: 'destructive',
            onPress: () =>
              remove(trade.id).catch((err) =>
                Alert.alert('Échec', (err as Error).message ?? 'erreur'),
              ),
          },
        ],
      );
    },
    [remove],
  );

  const openTrades = useMemo(() => trades.filter((t) => t.status === 'open'), [trades]);
  const closedTrades = useMemo(() => trades.filter((t) => t.status === 'closed'), [trades]);

  const renderTrade = (trade: ManualTrade) => {
    const dirColor = directionColor(trade.direction);
    const align = alignmentLabel(trade.tik_alignment);
    const res = trade.result_pct;
    const resColor = res === null ? Cosmic.text : res >= 0 ? Cosmic.long : Cosmic.short;
    return (
      <View key={trade.id} style={styles.row}>
        <View style={styles.rowLine}>
          <Text style={styles.entity}>{trade.entity_id}</Text>
          <View style={[styles.tag, { backgroundColor: dirColor + '22', borderColor: dirColor + '66' }]}>
            <Text style={[styles.tagText, { color: dirColor }]}>{trade.direction.toUpperCase()}</Text>
          </View>
          <Text style={styles.lots}>{trade.size_lots} lot</Text>
          <Text style={styles.timestamp}>{timeAgo(trade.entry_time)}</Text>
        </View>
        <View style={styles.rowLine}>
          <Text style={styles.priceText}>
            {trade.status === 'closed'
              ? `${trade.entry_price} → ${trade.exit_price}`
              : `@ ${trade.entry_price}`}
          </Text>
          {trade.status === 'closed' && res !== null ? (
            <Text style={[styles.result, { color: resColor }]}>
              {res >= 0 ? '+' : ''}
              {res.toFixed(2)}%
            </Text>
          ) : null}
          <View style={[styles.alignTag, { borderColor: align.color }]}>
            <Text style={[styles.alignLabel, { color: align.color }]}>
              {align.text}
              {trade.tik_veracity !== null ? ` ${(trade.tik_veracity * 100).toFixed(0)}%` : ''}
            </Text>
          </View>
        </View>
        {trade.note ? <Text style={styles.note}>{trade.note}</Text> : null}
        <View style={styles.rowActions}>
          {trade.status === 'open' ? (
            <Pressable
              onPress={() => onClose(trade)}
              style={({ pressed }) => [styles.actionBtn, { opacity: pressed ? 0.6 : 1 }]}>
              <Text style={styles.actionLabel}>Clôturer</Text>
            </Pressable>
          ) : null}
          <Pressable
            onPress={() => onDelete(trade)}
            style={({ pressed }) => [styles.deleteBtn, { opacity: pressed ? 0.5 : 0.7 }]}>
            <Text style={styles.deleteLabel}>Supprimer</Text>
          </Pressable>
        </View>
      </View>
    );
  };

  return (
    <CosmicBackground>
      <View style={[styles.container, { paddingTop: insets.top + 8 }]}>
        <KeyboardAvoidingView
          style={styles.flex}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <ScrollView
            contentContainerStyle={styles.scroll}
            keyboardShouldPersistTaps="handled"
            refreshControl={
              <RefreshControl refreshing={loading} onRefresh={refresh} tintColor={Cosmic.accent} />
            }>
            <Text style={styles.title}>Carnet de trades</Text>
            <Text style={styles.subtitle}>
              {"Tes vrais trades + ce que disait Tik à l'entrée. Objectif : mesurer si trader avec " +
                "Tik t'a mieux réussi que contre ou sans."}
            </Text>

            {!isAuthenticated ? (
              <Text style={styles.warn}>Connecte-toi (onglet Config) pour utiliser le carnet.</Text>
            ) : null}
            {error ? <Text style={styles.warn}>Erreur : {error}</Text> : null}

            <JournalStatsCard stats={stats} />

            {/* Bouton + formulaire d'ouverture */}
            <Pressable
              onPress={() => setShowForm((v) => !v)}
              style={({ pressed }) => [styles.newBtn, { opacity: pressed ? 0.8 : 1 }]}>
              <Text style={styles.newBtnLabel}>{showForm ? '× Fermer' : '+ Nouveau trade'}</Text>
            </Pressable>

            {showForm ? (
              <View style={styles.form}>
                {/* Actif */}
                <Text style={styles.fieldLabel}>Actif</Text>
                <View style={styles.toggleRow}>
                  {(['BTC', 'GOLD'] as Entity[]).map((e) => {
                    const active = entity === e;
                    return (
                      <Pressable
                        key={e}
                        onPress={() => setEntity(e)}
                        style={[
                          styles.toggle,
                          active
                            ? { backgroundColor: Cosmic.accent, borderColor: Cosmic.accent }
                            : { borderColor: Cosmic.borderStrong },
                        ]}>
                        <Text style={active ? styles.toggleActiveLabel : styles.toggleLabel}>{e}</Text>
                      </Pressable>
                    );
                  })}
                </View>

                {/* Sens */}
                <Text style={styles.fieldLabel}>Sens</Text>
                <View style={styles.toggleRow}>
                  {(['long', 'short'] as Direction[]).map((d) => {
                    const active = direction === d;
                    const dc = directionColor(d);
                    return (
                      <Pressable
                        key={d}
                        onPress={() => setDirection(d)}
                        style={[
                          styles.toggle,
                          active
                            ? { backgroundColor: dc, borderColor: dc }
                            : { borderColor: Cosmic.borderStrong },
                        ]}>
                        <Text style={active ? styles.toggleActiveLabel : styles.toggleLabel}>
                          {d.toUpperCase()}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>

                <Text style={styles.fieldLabel}>{"Prix d'entrée"}</Text>
                <TextInput
                  value={entryPrice}
                  onChangeText={setEntryPrice}
                  keyboardType="decimal-pad"
                  placeholder="ex : 64250"
                  placeholderTextColor={PLACEHOLDER}
                  style={styles.input}
                />

                <Text style={styles.fieldLabel}>Taille (lots MT5)</Text>
                <TextInput
                  value={sizeLots}
                  onChangeText={setSizeLots}
                  keyboardType="decimal-pad"
                  placeholder="ex : 0.10"
                  placeholderTextColor={PLACEHOLDER}
                  style={styles.input}
                />

                <View style={styles.twoCol}>
                  <View style={styles.col}>
                    <Text style={styles.fieldLabel}>Stop (optionnel)</Text>
                    <TextInput
                      value={stopPrice}
                      onChangeText={setStopPrice}
                      keyboardType="decimal-pad"
                      placeholder="—"
                      placeholderTextColor={PLACEHOLDER}
                      style={styles.input}
                    />
                  </View>
                  <View style={styles.col}>
                    <Text style={styles.fieldLabel}>Cible (optionnel)</Text>
                    <TextInput
                      value={targetPrice}
                      onChangeText={setTargetPrice}
                      keyboardType="decimal-pad"
                      placeholder="—"
                      placeholderTextColor={PLACEHOLDER}
                      style={styles.input}
                    />
                  </View>
                </View>

                <Text style={styles.fieldLabel}>Note (optionnel)</Text>
                <TextInput
                  value={note}
                  onChangeText={setNote}
                  placeholder="ex : RSI bearish, EMA20<50…"
                  placeholderTextColor={PLACEHOLDER}
                  multiline
                  style={[styles.input, styles.noteInput]}
                />

                {/* Contexte Tik */}
                <View style={styles.tikBox}>
                  <Text style={styles.tikTitle}>🧠 Contexte Tik (auto)</Text>
                  {tik && tik.direction ? (
                    <Text style={styles.tikText}>
                      Swing {entity} = {tik.direction.toUpperCase()}
                      {tik.veracity !== null ? ` · véracité ${tik.veracity.toFixed(2)}` : ''}
                      {'  →  '}
                      {alignmentPreview(direction, tik)}
                    </Text>
                  ) : (
                    <Text style={styles.tikText}>
                      Pas de signal swing {entity} directionnel récent → trade « sans signal ».
                    </Text>
                  )}
                </View>

                <Pressable
                  onPress={submit}
                  disabled={submitting}
                  style={({ pressed }) => [
                    styles.saveBtn,
                    { opacity: submitting || pressed ? 0.7 : 1 },
                  ]}>
                  <Text style={styles.saveBtnLabel}>
                    {submitting ? 'Enregistrement…' : 'Enregistrer le trade'}
                  </Text>
                </Pressable>
              </View>
            ) : null}

            {/* Listes */}
            {openTrades.length > 0 ? (
              <>
                <Text style={styles.listHeader}>EN COURS ({openTrades.length})</Text>
                {openTrades.map(renderTrade)}
              </>
            ) : null}

            {closedTrades.length > 0 ? (
              <>
                <Text style={styles.listHeader}>CLÔTURÉS ({closedTrades.length})</Text>
                {closedTrades.map(renderTrade)}
              </>
            ) : null}

            {isAuthenticated && trades.length === 0 && !loading ? (
              <Text style={styles.emptyText}>
                Aucun trade encore. Tape « + Nouveau trade » pour enregistrer ton premier.
              </Text>
            ) : null}
          </ScrollView>
        </KeyboardAvoidingView>
      </View>
    </CosmicBackground>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, paddingHorizontal: 16 },
  flex: { flex: 1 },
  scroll: { paddingBottom: 40, gap: 10 },
  title: {
    ...TitleShadow.glow,
    fontFamily: serifTitleFamily,
    color: Cosmic.text,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  subtitle: { color: Cosmic.textDim, fontSize: 13, lineHeight: 18 },
  warn: { fontSize: 13, color: Cosmic.neutral },
  newBtn: {
    backgroundColor: Cosmic.accent,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
    marginTop: 4,
  },
  newBtnLabel: { color: Cosmic.bgDeep, fontWeight: '800', fontSize: 15 },
  form: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 6,
  },
  fieldLabel: { color: Cosmic.textDim, fontSize: 12, marginTop: 4 },
  input: {
    backgroundColor: Cosmic.cardAlt,
    borderColor: Cosmic.borderStrong,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    color: Cosmic.text,
  },
  noteInput: { minHeight: 44, textAlignVertical: 'top' },
  toggleRow: { flexDirection: 'row', gap: 8 },
  toggle: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: 'center',
  },
  toggleLabel: { color: Cosmic.textDim, fontWeight: '600' },
  toggleActiveLabel: { color: Cosmic.bgDeep, fontWeight: '800' },
  twoCol: { flexDirection: 'row', gap: 10 },
  col: { flex: 1 },
  tikBox: {
    backgroundColor: Cosmic.cardAlt,
    borderColor: Cosmic.borderStrong,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderRadius: 8,
    padding: 10,
    marginTop: 6,
    gap: 2,
  },
  tikTitle: { color: Cosmic.text, fontSize: 12, fontWeight: '700' },
  tikText: { color: Cosmic.textDim, fontSize: 13, lineHeight: 18 },
  saveBtn: {
    backgroundColor: Cosmic.accent,
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: 'center',
    marginTop: 8,
  },
  saveBtnLabel: { color: Cosmic.bgDeep, fontWeight: '800', fontSize: 15 },
  listHeader: {
    color: Cosmic.textFaint,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.5,
    marginTop: 10,
  },
  row: {
    backgroundColor: Cosmic.card,
    borderColor: Cosmic.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 6,
  },
  rowLine: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  entity: { color: Cosmic.text, fontSize: 15, fontWeight: '700' },
  tag: {
    borderWidth: 1,
    borderRadius: 7,
    paddingVertical: 3,
    paddingHorizontal: 8,
    minWidth: 58,
    alignItems: 'center',
  },
  tagText: { fontSize: 11, fontWeight: '800', letterSpacing: 0.5 },
  lots: { color: Cosmic.textDim, fontSize: 12 },
  timestamp: { color: Cosmic.textFaint, fontSize: 11, marginLeft: 'auto' },
  priceText: { color: Cosmic.text, fontSize: 14 },
  result: { fontSize: 15, fontWeight: '700' },
  alignTag: {
    borderWidth: 1,
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 2,
    marginLeft: 'auto',
  },
  alignLabel: { fontSize: 11, fontWeight: '700' },
  note: { color: Cosmic.textDim, fontSize: 13, fontStyle: 'italic' },
  rowActions: { flexDirection: 'row', gap: 12, alignItems: 'center', marginTop: 2 },
  actionBtn: {
    borderWidth: 1,
    borderColor: Cosmic.accent,
    borderRadius: 16,
    paddingVertical: 6,
    paddingHorizontal: 14,
  },
  actionLabel: { color: Cosmic.accent, fontSize: 13, fontWeight: '600' },
  deleteBtn: { paddingVertical: 6, marginLeft: 'auto' },
  deleteLabel: { fontSize: 12, color: Cosmic.short },
  emptyText: {
    color: Cosmic.textDim,
    textAlign: 'center',
    fontSize: 14,
    lineHeight: 20,
    marginTop: 20,
  },
});
