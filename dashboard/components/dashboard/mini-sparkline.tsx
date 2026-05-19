import { StyleSheet, View } from 'react-native';
import Svg, { Circle, Polyline, Line } from 'react-native-svg';

import { ThemedText } from '@/components/themed-text';

export interface MiniSparklineProps {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  strokeWidth?: number;
  yMin?: number;
  yMax?: number;
  thresholds?: number[];
  thresholdColor?: string;
  /** Seuil mis en évidence (ligne pleine colorée vs pointillée grise pour `thresholds`).
      F7 audit UX : seuil personnel Garde-fou 2-bis transitoire. */
  personalThreshold?: number;
  personalThresholdColor?: string;
  emptyMessage?: string;
  autoScale?: boolean;
  minAmplitude?: number;
}

export function MiniSparkline({
  values,
  width = 280,
  height = 56,
  color = '#0a7ea4',
  strokeWidth = 2,
  yMin = 0,
  yMax = 1,
  thresholds,
  thresholdColor = 'rgba(127, 140, 141, 0.3)',
  personalThreshold,
  personalThresholdColor = '#27ae60',
  emptyMessage = 'Pas assez de points pour tracer',
  autoScale = false,
  minAmplitude = 0.1,
}: MiniSparklineProps) {
  if (values.length < 2) {
    return (
      <View style={[styles.empty, { width, height }]}>
        <ThemedText style={styles.emptyText}>{emptyMessage}</ThemedText>
      </View>
    );
  }

  let effectiveMin = yMin;
  let effectiveMax = yMax;
  if (autoScale) {
    const refs = [
      ...values,
      ...(thresholds ?? []),
      ...(personalThreshold !== undefined ? [personalThreshold] : []),
    ];
    const dataMin = Math.min(...refs);
    const dataMax = Math.max(...refs);
    const span = Math.max(dataMax - dataMin, minAmplitude);
    const pad = span * 0.1;
    effectiveMin = Math.max(0, dataMin - pad);
    effectiveMax = Math.min(1, dataMax + pad);
    if (effectiveMax - effectiveMin < minAmplitude) {
      const center = (effectiveMin + effectiveMax) / 2;
      effectiveMin = Math.max(0, center - minAmplitude / 2);
      effectiveMax = Math.min(1, center + minAmplitude / 2);
    }
  }

  const range = Math.max(effectiveMax - effectiveMin, Number.EPSILON);
  const padding = strokeWidth + 1;
  const innerW = width - padding * 2;
  const innerH = height - padding * 2;

  const project = (v: number, i: number) => {
    const x = padding + (i / (values.length - 1)) * innerW;
    const clamped = Math.max(effectiveMin, Math.min(effectiveMax, v));
    const norm = (clamped - effectiveMin) / range;
    const y = padding + (1 - norm) * innerH;
    return { x, y };
  };

  const points = values.map((v, i) => {
    const { x, y } = project(v, i);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const last = project(values[values.length - 1], values.length - 1);

  return (
    <View style={{ width, height }}>
      <Svg width={width} height={height}>
        {thresholds?.map((t, i) => {
          if (t < effectiveMin || t > effectiveMax) return null;
          const norm = (t - effectiveMin) / range;
          const y = padding + (1 - norm) * innerH;
          return (
            <Line
              key={`t${i}`}
              x1={padding}
              x2={width - padding}
              y1={y}
              y2={y}
              stroke={thresholdColor}
              strokeDasharray="4 4"
              strokeWidth={1}
            />
          );
        })}
        {personalThreshold !== undefined &&
        personalThreshold >= effectiveMin &&
        personalThreshold <= effectiveMax ? (
          <Line
            x1={padding}
            x2={width - padding}
            y1={padding + (1 - (personalThreshold - effectiveMin) / range) * innerH}
            y2={padding + (1 - (personalThreshold - effectiveMin) / range) * innerH}
            stroke={personalThresholdColor}
            strokeWidth={1.5}
          />
        ) : null}
        <Polyline
          points={points.join(' ')}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <Circle cx={last.x} cy={last.y} r={strokeWidth + 1} fill={color} />
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  empty: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyText: {
    fontSize: 11,
    opacity: 0.5,
  },
});
