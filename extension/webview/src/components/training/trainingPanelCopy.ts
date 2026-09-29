/**
 * Shared training-panel copy (§十五: eight languages, no zh/en binary).
 *
 * Covers the time-of-day greetings and duration formatting shared by
 * TrainingWelcomePanel / TrainingMotivationPanel / TrainingRhythmPanel.
 * zh-CN and en-US strings stay byte-identical to the pre-migration output.
 */
import type { ComposerLanguage } from "../../lib/types";

export type TrainingTimeGreetingBucket =
  | "lateNight"
  | "earlyMorning"
  | "morning"
  | "noon"
  | "afternoon"
  | "evening"
  | "night";

const TIME_GREETING_COPY: Record<ComposerLanguage, Record<TrainingTimeGreetingBucket, string>> = {
  "zh-CN": {
    lateNight: "夜间",
    earlyMorning: "清晨",
    morning: "上午",
    noon: "午间",
    afternoon: "下午",
    evening: "晚上",
    night: "夜间",
  },
  "en-US": {
    lateNight: "Late night",
    earlyMorning: "Early morning",
    morning: "Morning",
    noon: "Noon",
    afternoon: "Afternoon",
    evening: "Evening",
    night: "Night",
  },
  "es-ES": {
    lateNight: "Madrugada",
    earlyMorning: "Primera hora",
    morning: "Mañana",
    noon: "Mediodía",
    afternoon: "Tarde",
    evening: "Noche",
    night: "Noche",
  },
  "fr-FR": {
    lateNight: "Nuit tardive",
    earlyMorning: "Tôt le matin",
    morning: "Matin",
    noon: "Midi",
    afternoon: "Après-midi",
    evening: "Soir",
    night: "Nuit",
  },
  "de-DE": {
    lateNight: "Späte Nacht",
    earlyMorning: "Früher Morgen",
    morning: "Vormittag",
    noon: "Mittag",
    afternoon: "Nachmittag",
    evening: "Abend",
    night: "Nacht",
  },
  "ja-JP": {
    lateNight: "夜間",
    earlyMorning: "早朝",
    morning: "午前",
    noon: "正午",
    afternoon: "午後",
    evening: "夜",
    night: "夜間",
  },
  "ko-KR": {
    lateNight: "야간",
    earlyMorning: "이른 아침",
    morning: "오전",
    noon: "정오",
    afternoon: "오후",
    evening: "저녁",
    night: "야간",
  },
  "pt-BR": {
    lateNight: "Madrugada",
    earlyMorning: "Manhã cedo",
    morning: "Manhã",
    noon: "Meio-dia",
    afternoon: "Tarde",
    evening: "Noite",
    night: "Noite",
  },
};

/** Greeting label for the hour-of-day buckets used by the welcome/motivation panels. */
export function timeOfDayGreeting(hour: number, language: ComposerLanguage): string {
  if (hour < 6) {
    return TIME_GREETING_COPY[language].lateNight;
  }
  if (hour < 9) {
    return TIME_GREETING_COPY[language].earlyMorning;
  }
  if (hour < 12) {
    return TIME_GREETING_COPY[language].morning;
  }
  if (hour < 14) {
    return TIME_GREETING_COPY[language].noon;
  }
  if (hour < 18) {
    return TIME_GREETING_COPY[language].afternoon;
  }
  if (hour < 21) {
    return TIME_GREETING_COPY[language].evening;
  }
  return TIME_GREETING_COPY[language].night;
}

export type TrainingTimePeriodBucket =
  | "preDawn"
  | "sunrise"
  | "lateMorning"
  | "midday"
  | "afternoon"
  | "dusk"
  | "night";

/** Prefix labels for the rhythm panel's review-slot time periods. */
const TIME_PERIOD_PREFIX_COPY: Record<ComposerLanguage, Record<TrainingTimePeriodBucket, string>> = {
  "zh-CN": {
    preDawn: "凌晨",
    sunrise: "早晨",
    lateMorning: "上午",
    midday: "中午",
    afternoon: "下午",
    dusk: "傍晚",
    night: "晚上",
  },
  "en-US": {
    preDawn: "Late night",
    sunrise: "Morning",
    lateMorning: "Late morning",
    midday: "Noon",
    afternoon: "Afternoon",
    dusk: "Evening",
    night: "Night",
  },
  "es-ES": {
    preDawn: "Madrugada",
    sunrise: "Mañana",
    lateMorning: "Media mañana",
    midday: "Mediodía",
    afternoon: "Tarde",
    dusk: "Atardecer",
    night: "Noche",
  },
  "fr-FR": {
    preDawn: "Nuit tardive",
    sunrise: "Matin",
    lateMorning: "Fin de matinée",
    midday: "Midi",
    afternoon: "Après-midi",
    dusk: "Début de soirée",
    night: "Soirée",
  },
  "de-DE": {
    preDawn: "Nacht",
    sunrise: "Morgen",
    lateMorning: "Vormittag",
    midday: "Mittag",
    afternoon: "Nachmittag",
    dusk: "Abend",
    night: "Nacht",
  },
  "ja-JP": {
    preDawn: "未明",
    sunrise: "朝",
    lateMorning: "午前",
    midday: "正午",
    afternoon: "午後",
    dusk: "夕方",
    night: "夜",
  },
  "ko-KR": {
    preDawn: "새벽",
    sunrise: "아침",
    lateMorning: "오전",
    midday: "낮",
    afternoon: "오후",
    dusk: "저녁",
    night: "밤",
  },
  "pt-BR": {
    preDawn: "Madrugada",
    sunrise: "Manhã",
    lateMorning: "Fim da manhã",
    midday: "Meio-dia",
    afternoon: "Tarde",
    dusk: "Fim de tarde",
    night: "Noite",
  },
};

/** Period prefix for the hour-of-day buckets used by the rhythm panel slots. */
export function timeOfDayPeriodPrefix(hour: number, language: ComposerLanguage): string {
  if (hour < 6) {
    return TIME_PERIOD_PREFIX_COPY[language].preDawn;
  }
  if (hour < 9) {
    return TIME_PERIOD_PREFIX_COPY[language].sunrise;
  }
  if (hour < 12) {
    return TIME_PERIOD_PREFIX_COPY[language].lateMorning;
  }
  if (hour < 14) {
    return TIME_PERIOD_PREFIX_COPY[language].midday;
  }
  if (hour < 18) {
    return TIME_PERIOD_PREFIX_COPY[language].afternoon;
  }
  if (hour < 21) {
    return TIME_PERIOD_PREFIX_COPY[language].dusk;
  }
  return TIME_PERIOD_PREFIX_COPY[language].night;
}

export interface TrainingDurationCopy {
  /** Label for durations under one minute (rhythm panel only). */
  underMinute: string;
  minutes: (amount: number) => string;
  hours: (amount: number) => string;
  mixed: (hours: number, minutes: number) => string;
}

const DURATION_COPY: Record<ComposerLanguage, TrainingDurationCopy> = {
  "zh-CN": {
    underMinute: "<1 分钟",
    minutes: (amount) => `${amount} 分钟`,
    hours: (amount) => `${amount} 小时`,
    mixed: (hours, minutes) => `${hours}h ${minutes}m`,
  },
  "en-US": {
    underMinute: "<1 min",
    minutes: (amount) => `${amount} min`,
    hours: (amount) => `${amount} hr`,
    mixed: (hours, minutes) => `${hours}hr ${minutes}min`,
  },
  "es-ES": {
    underMinute: "<1 min",
    minutes: (amount) => `${amount} min`,
    hours: (amount) => `${amount} h`,
    mixed: (hours, minutes) => `${hours} h ${minutes} min`,
  },
  "fr-FR": {
    underMinute: "<1 min",
    minutes: (amount) => `${amount} min`,
    hours: (amount) => `${amount} h`,
    mixed: (hours, minutes) => `${hours} h ${minutes} min`,
  },
  "de-DE": {
    underMinute: "<1 Min.",
    minutes: (amount) => `${amount} Min.`,
    hours: (amount) => `${amount} Std.`,
    mixed: (hours, minutes) => `${hours} Std. ${minutes} Min.`,
  },
  "ja-JP": {
    underMinute: "1分未満",
    minutes: (amount) => `${amount}分`,
    hours: (amount) => `${amount}時間`,
    mixed: (hours, minutes) => `${hours}時間${minutes}分`,
  },
  "ko-KR": {
    underMinute: "1분 미만",
    minutes: (amount) => `${amount}분`,
    hours: (amount) => `${amount}시간`,
    mixed: (hours, minutes) => `${hours}시간 ${minutes}분`,
  },
  "pt-BR": {
    underMinute: "<1 min",
    minutes: (amount) => `${amount} min`,
    hours: (amount) => `${amount} h`,
    mixed: (hours, minutes) => `${hours} h ${minutes} min`,
  },
};

export function trainingDurationCopy(language: ComposerLanguage): TrainingDurationCopy {
  return DURATION_COPY[language];
}
