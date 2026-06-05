/**
 * Écran Carnet de trades manuels (Levier B 2026-06-03).
 *
 * Journal des vrais trades de la trader : ouverture (avec snapshot du contexte
 * Tik à l'entrée), liste ouverts/clôturés, clôture (→ résultat %), bilan
 * « Tik t'a-t-il aidée ? ». Stockage serveur (VPS) via /api/v1/trades.
 *
 * Taille saisie en lots MT5 (choix trader). Résultat affiché en % (price-based,
 * sans spec contrat broker — cf. memory mt5-points-calibration-todo).
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
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { JournalStatsCard } from '@/components/journal/journal-stats-card';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { getLatestSignals } from '@/src/api/endpoints';
import type { ManualTrade } from '@/src/api/types';
import { useAuth } from '@/src/auth/AuthContext';
import { useTrades } from '@/src/journal/useTrades';
import { timeAgo } from '@/src/utils/time';

type Entity = 'BTC' | 'GOLD';
type Direction = 'long' | 'short';

function directionColor(direction: string): string {
  if (direction === 'long') return '#27ae60';
  if (direction === 'short') return '#c0392b';
  return '#7f8c8d';
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
      return { text: 'avec Tik', color: '#27ae60' };
    case 'against':
      return { text: 'contre Tik', color: '#c0392b' };
    default:
      return { text: 'sans signal', color: '#7f8c8d' };
  }
}

export default function JournalScreen() {
  const insets = useSafeAreaInsets();
  const colorScheme = useColorScheme() ?? 'light';
  const palette = Colors[colorScheme];
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

  const inputStyle = [styles.input, { color: palette.text, borderColor: palette.icon }];
  const placeholderColor = colorScheme === 'dark' ? '#666' : '#999';

  const renderTrade = (trade: ManualTrade) => {
    const dirColor = directionColor(trade.direction);
    const align = alignmentLabel(trade.tik_alignment);
    const res = trade.result_pct;
    const resColor = res === null ? palette.text : res >= 0 ? '#27ae60' : '#c0392b';
    return (
      <View key={trade.id} style={[styles.row, { borderColor: palette.icon }]}>
        <View style={styles.rowLine}>
          <ThemedText type="defaultSemiBold">{trade.entity_id}</ThemedText>
          <View style={[styles.badge, { backgroundColor: dirColor }]}>
            <ThemedText style={styles.badgeLabel}>{trade.direction.toUpperCase()}</ThemedText>
          </View>
          <ThemedText style={styles.lots}>{trade.size_lots} lot</ThemedText>
          <ThemedText style={styles.timestamp}>{timeAgo(trade.entry_time)}</ThemedText>
        </View>
        <View style={styles.rowLine}>
          <ThemedText style={styles.priceText}>
            {trade.status === 'closed'
              ? `${trade.entry_price} → ${trade.exit_price}`
              : `@ ${trade.entry_price}`}
          </ThemedText>
          {trade.status === 'closed' && res !== null ? (
            <ThemedText style={[styles.result, { color: resColor }]}>
              {res >= 0 ? '+' : ''}
              {res.toFixed(2)}%
            </ThemedText>
          ) : null}
          <View style={[styles.alignTag, { borderColor: align.color }]}>
            <ThemedText style={[styles.alignLabel, { color: align.color }]}>
              {align.text}
              {trade.tik_veracity !== null ? ` ${(trade.tik_veracity * 100).toFixed(0)}%` : ''}
            </ThemedText>
          </View>
        </View>
        {trade.note ? <ThemedText style={styles.note}>{trade.note}</ThemedText> : null}
        <View style={styles.rowActions}>
          {trade.status === 'open' ? (
            <Pressable
              onPress={() => onClose(trade)}
              style={({ pressed }) => [
                styles.actionBtn,
                { borderColor: palette.tint, opacity: pressed ? 0.6 : 1 },
              ]}>
              <ThemedText style={{ color: palette.tint, fontSize: 13 }}>Clôturer</ThemedText>
            </Pressable>
          ) : null}
          <Pressable
            onPress={() => onDelete(trade)}
            style={({ pressed }) => [styles.deleteBtn, { opacity: pressed ? 0.5 : 0.7 }]}>
            <ThemedText style={styles.deleteLabel}>Supprimer</ThemedText>
          </Pressable>
        </View>
      </View>
    );
  };

  return (
    <ThemedView style={[styles.container, { paddingTop: insets.top + 8 }]}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={loading} onRefresh={refresh} />}>
          <ThemedText type="title">Carnet de trades</ThemedText>
          <ThemedText style={styles.subtitle}>
            Tes vrais trades + ce que disait Tik à l&apos;entrée. Objectif : mesurer si trader
            avec Tik t&apos;a mieux réussi que contre ou sans.
          </ThemedText>

          {!isAuthenticated ? (
            <ThemedText style={styles.warn}>Connecte-toi (onglet Config) pour utiliser le carnet.</ThemedText>
          ) : null}
          {error ? <ThemedText style={styles.warn}>Erreur : {error}</ThemedText> : null}

          <JournalStatsCard stats={stats} />

          {/* Bouton + formulaire d'ouverture */}
          <Pressable
            onPress={() => setShowForm((v) => !v)}
            style={({ pressed }) => [
              styles.newBtn,
              { backgroundColor: palette.tint, opacity: pressed ? 0.8 : 1 },
            ]}>
            <ThemedText style={styles.newBtnLabel}>
              {showForm ? '× Fermer' : '+ Nouveau trade'}
            </ThemedText>
          </Pressable>

          {showForm ? (
            <View style={[styles.form, { borderColor: palette.icon }]}>
              {/* Actif */}
              <ThemedText style={styles.fieldLabel}>Actif</ThemedText>
              <View style={styles.toggleRow}>
                {(['BTC', 'GOLD'] as Entity[]).map((e) => (
                  <Pressable
                    key={e}
                    onPress={() => setEntity(e)}
                    style={[
                      styles.toggle,
                      { borderColor: palette.icon },
                      entity === e ? { backgroundColor: palette.tint } : null,
                    ]}>
                    <ThemedText style={entity === e ? styles.toggleActiveLabel : undefined}>
                      {e}
                    </ThemedText>
                  </Pressable>
                ))}
              </View>

              {/* Sens */}
              <ThemedText style={styles.fieldLabel}>Sens</ThemedText>
              <View style={styles.toggleRow}>
                {(['long', 'short'] as Direction[]).map((d) => (
                  <Pressable
                    key={d}
                    onPress={() => setDirection(d)}
                    style={[
                      styles.toggle,
                      { borderColor: palette.icon },
                      direction === d ? { backgroundColor: directionColor(d) } : null,
                    ]}>
                    <ThemedText style={direction === d ? styles.toggleActiveLabel : undefined}>
                      {d.toUpperCase()}
                    </ThemedText>
                  </Pressable>
                ))}
              </View>

              <ThemedText style={styles.fieldLabel}>Prix d&apos;entrée</ThemedText>
              <TextInput
                value={entryPrice}
                onChangeText={setEntryPrice}
                keyboardType="decimal-pad"
                placeholder="ex : 64250"
                placeholderTextColor={placeholderColor}
                style={inputStyle}
              />

              <ThemedText style={styles.fieldLabel}>Taille (lots MT5)</ThemedText>
              <TextInput
                value={sizeLots}
                onChangeText={setSizeLots}
                keyboardType="decimal-pad"
                placeholder="ex : 0.10"
                placeholderTextColor={placeholderColor}
                style={inputStyle}
              />

              <View style={styles.twoCol}>
                <View style={styles.col}>
                  <ThemedText style={styles.fieldLabel}>Stop (optionnel)</ThemedText>
                  <TextInput
                    value={stopPrice}
                    onChangeText={setStopPrice}
                    keyboardType="decimal-pad"
                    placeholder="—"
                    placeholderTextColor={placeholderColor}
                    style={inputStyle}
                  />
                </View>
                <View style={styles.col}>
                  <ThemedText style={styles.fieldLabel}>Cible (optionnel)</ThemedText>
                  <TextInput
                    value={targetPrice}
                    onChangeText={setTargetPrice}
                    keyboardType="decimal-pad"
                    placeholder="—"
                    placeholderTextColor={placeholderColor}
                    style={inputStyle}
                  />
                </View>
              </View>

              <ThemedText style={styles.fieldLabel}>Note (optionnel)</ThemedText>
              <TextInput
                value={note}
                onChangeText={setNote}
                placeholder="ex : RSI bearish, EMA20<50…"
                placeholderTextColor={placeholderColor}
                multiline
                style={[inputStyle, styles.noteInput]}
              />

              {/* Contexte Tik */}
              <View style={[styles.tikBox, { borderColor: palette.icon }]}>
                <ThemedText style={styles.tikTitle}>🧠 Contexte Tik (auto)</ThemedText>
                {tik && tik.direction ? (
                  <ThemedText style={styles.tikText}>
                    Swing {entity} = {tik.direction.toUpperCase()}
                    {tik.veracity !== null ? ` · véracité ${tik.veracity.toFixed(2)}` : ''}
                    {'  →  '}
                    {alignmentPreview(direction, tik)}
                  </ThemedText>
                ) : (
                  <ThemedText style={styles.tikText}>
                    Pas de signal swing {entity} directionnel récent → trade « sans signal ».
                  </ThemedText>
                )}
              </View>

              <Pressable
                onPress={submit}
                disabled={submitting}
                style={({ pressed }) => [
                  styles.saveBtn,
                  { backgroundColor: palette.tint, opacity: submitting || pressed ? 0.7 : 1 },
                ]}>
                <ThemedText style={styles.saveBtnLabel}>
                  {submitting ? 'Enregistrement…' : 'Enregistrer le trade'}
                </ThemedText>
              </Pressable>
            </View>
          ) : null}

          {/* Listes */}
          {openTrades.length > 0 ? (
            <>
              <ThemedText style={styles.listHeader}>EN COURS ({openTrades.length})</ThemedText>
              {openTrades.map(renderTrade)}
            </>
          ) : null}

          {closedTrades.length > 0 ? (
            <>
              <ThemedText style={styles.listHeader}>CLÔTURÉS ({closedTrades.length})</ThemedText>
              {closedTrades.map(renderTrade)}
            </>
          ) : null}

          {isAuthenticated && trades.length === 0 && !loading ? (
            <ThemedText style={styles.emptyText}>
              Aucun trade encore. Tape « + Nouveau trade » pour enregistrer ton premier.
            </ThemedText>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, paddingHorizontal: 16 },
  flex: { flex: 1 },
  scroll: { paddingBottom: 40, gap: 10 },
  subtitle: { fontSize: 13, opacity: 0.7 },
  warn: { fontSize: 13, color: '#e67e22' },
  newBtn: {
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
    marginTop: 4,
  },
  newBtnLabel: { color: '#ffffff', fontWeight: '700', fontSize: 15 },
  form: {
    borderWidth: 1,
    borderRadius: 10,
    padding: 14,
    gap: 6,
  },
  fieldLabel: { fontSize: 12, opacity: 0.7, marginTop: 4 },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
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
  toggleActiveLabel: { color: '#ffffff', fontWeight: '700' },
  twoCol: { flexDirection: 'row', gap: 10 },
  col: { flex: 1 },
  tikBox: {
    borderWidth: 1,
    borderStyle: 'dashed',
    borderRadius: 8,
    padding: 10,
    marginTop: 6,
    gap: 2,
  },
  tikTitle: { fontSize: 12, fontWeight: '600' },
  tikText: { fontSize: 13, opacity: 0.85 },
  saveBtn: {
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: 'center',
    marginTop: 8,
  },
  saveBtnLabel: { color: '#ffffff', fontWeight: '700', fontSize: 15 },
  listHeader: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.5,
    opacity: 0.6,
    marginTop: 10,
  },
  row: {
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    gap: 6,
  },
  rowLine: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 4 },
  badgeLabel: { color: '#ffffff', fontSize: 10, fontWeight: '700', letterSpacing: 0.4 },
  lots: { fontSize: 12, opacity: 0.7 },
  timestamp: { fontSize: 11, opacity: 0.6, marginLeft: 'auto' },
  priceText: { fontSize: 14 },
  result: { fontSize: 15, fontWeight: '700' },
  alignTag: {
    borderWidth: 1,
    borderRadius: 4,
    paddingHorizontal: 8,
    paddingVertical: 2,
    marginLeft: 'auto',
  },
  alignLabel: { fontSize: 11, fontWeight: '600' },
  note: { fontSize: 13, opacity: 0.7, fontStyle: 'italic' },
  rowActions: { flexDirection: 'row', gap: 12, alignItems: 'center', marginTop: 2 },
  actionBtn: {
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 6,
    paddingHorizontal: 14,
  },
  deleteBtn: { paddingVertical: 6, marginLeft: 'auto' },
  deleteLabel: { fontSize: 12, color: '#c0392b' },
  emptyText: {
    textAlign: 'center',
    opacity: 0.6,
    fontSize: 14,
    lineHeight: 20,
    marginTop: 20,
  },
});
