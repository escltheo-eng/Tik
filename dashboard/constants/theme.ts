/**
 * Below are the colors that are used in the app. The colors are defined in the light and dark mode.
 * There are many other ways to style your app. For example, [Nativewind](https://www.nativewind.dev/), [Tamagui](https://tamagui.dev/), [unistyles](https://reactnativeunistyles.vercel.app), etc.
 */

import { Platform } from 'react-native';

const tintColorLight = '#0a7ea4';
// 2026-05-17 : `#fff` posait un bug (boutons primary + pills actives avec
// `backgroundColor: palette.tint` devenaient blancs avec texte blanc =
// invisible). Choix d'un bleu accessible plus clair que le tint light
// pour rester lisible sur fond `#151718` du mode sombre. Texte blanc
// hardcodé sur ces boutons reste lisible sur ce bleu.
const tintColorDark = '#4dabf5';

export const Colors = {
  light: {
    text: '#11181C',
    background: '#fff',
    tint: tintColorLight,
    icon: '#687076',
    tabIconDefault: '#687076',
    tabIconSelected: tintColorLight,
  },
  // Mode sombre reteinté aux couleurs cosmiques (refonte γ, bout 5). L'app est
  // forcée en sombre (cf. hooks/use-color-scheme) → ce thème pilote TOUS les
  // écrans encore « thémés » (Home/Watchlist/Carnet/Alerts/Config). Le `tint`
  // reste volontairement bleu (pas ambre) : des boutons portent du texte blanc
  // hardcodé, et blanc-sur-ambre serait illisible (cf. note tintColorDark).
  dark: {
    text: '#eef2fa',
    background: '#0a0c14',
    tint: tintColorDark,
    icon: '#8893ad',
    tabIconDefault: '#8893ad',
    tabIconSelected: tintColorDark,
  },
};

export const Fonts = Platform.select({
  ios: {
    /** iOS `UIFontDescriptorSystemDesignDefault` */
    sans: 'system-ui',
    /** iOS `UIFontDescriptorSystemDesignSerif` */
    serif: 'ui-serif',
    /** iOS `UIFontDescriptorSystemDesignRounded` */
    rounded: 'ui-rounded',
    /** iOS `UIFontDescriptorSystemDesignMonospaced` */
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    serif: "Georgia, 'Times New Roman', serif",
    rounded: "'SF Pro Rounded', 'Hiragino Maru Gothic ProN', Meiryo, 'MS PGothic', sans-serif",
    mono: "SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
  },
});
