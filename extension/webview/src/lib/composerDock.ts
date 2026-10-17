import { PRIMARY_DESTINATIONS } from "./workbenchDestinations";
import type { ActiveWorkbenchView } from "./types";

/**
 * Persistent dock composer governance (§3.7).
 *
 * Product ruling: Coach / Learning / Resources keep a persistent bottom
 * composer. One thread (the single coach conversation), one component (the
 * shared CoachComposer instance in the app footer), surface-keyed drafts,
 * automatic context anchor chips, and a send-jump/stay preference.
 *
 * Governance semantics that must never drift:
 * - Training never docks (FocusedPractice owns its phase inputs; the 5-phase
 *   state machine and the verification gate must not be bypassed by a free
 *   composer). Progress and Settings are utilities, not work surfaces.
 * - A hidden surface never writes a draft: each surface owns a separate
 *   draft scope key (red line 3; pins the App.tsx:5129-class overwrite bug).
 * - Streaming mutex: the dock is the SAME component instance as the coach
 *   composer, so the existing busy/read-only state covers every surface.
 */

export const DOCK_SURFACES = ["coach", "plan", "resources"] as const;
export type ComposerDockSurface = (typeof DOCK_SURFACES)[number];

/** True when the persistent dock composer is mounted for this route. */
export function docksComposer(route: ActiveWorkbenchView): boolean {
  return (PRIMARY_DESTINATIONS as readonly string[]).includes(route);
}

/**
 * Draft scope key for one surface. Coach keeps the historical session-level
 * key so existing drafts and their tests are untouched; Learning and
 * Resources isolate drafts per surface (never shared, never overwritten by
 * a hidden surface).
 */
export function composerDockDraftScope(
  surface: ActiveWorkbenchView,
  composerSessionKey: string,
): string {
  if (surface === "coach" || !docksComposer(surface)) {
    return composerSessionKey;
  }
  return `${composerSessionKey}\u0000dock:${surface}`;
}

/** Send-and-jump (default) versus send-and-stay, per §3.7 red line 5. */
export type DockSendPreference = "jump" | "stay";

export function normalizeDockSendPreference(value: unknown): DockSendPreference {
  return value === "stay" ? "stay" : "jump";
}

/**
 * Where a send from this surface navigates under the given preference.
 * "jump" switches to Coach to watch the streamed answer (default);
 * "stay" keeps the working surface and relies on the returnToSurface banner.
 */
export function dockSendNavigation(
  preference: DockSendPreference,
  surface: ActiveWorkbenchView,
): "jump_to_coach" | "stay" {
  if (preference === "stay" && surface !== "coach") {
    return "stay";
  }
  return "jump_to_coach";
}

export interface DockContextAnchor {
  /** Stable identity for the chip (dedupe/keys). */
  id: string;
  /** Short chip label shown in the dock strip. */
  label: string;
  /** Exact context line appended to the outgoing message. */
  text: string;
}

export interface DockAnchorContext {
  /** Learning: active stage title (resolved by the caller from the live plan). */
  stageTitle?: string | null;
  /** Learning: "step i / n" progress label, already localized. */
  stageProgress?: string | null;
  /** Resources: current resource / selection label. */
  resourceLabel?: string | null;
}

/**
 * Automatic context anchoring (§3.7 red line 4): a send from Learning
 * carries the current stage; a send from Resources carries the open
 * resource/selection. The chip is removable — `suppressed` lets the learner
 * strip the anchor for one surface until the context changes.
 */
export function resolveDockContextAnchor(
  surface: ActiveWorkbenchView,
  context: DockAnchorContext,
  suppressed = false,
): DockContextAnchor | null {
  if (suppressed) {
    return null;
  }
  if (surface === "plan") {
    const stage = context.stageTitle?.trim();
    if (!stage) {
      return null;
    }
    const progress = context.stageProgress?.trim();
    const label = progress ? `${progress} · ${stage}` : stage;
    return {
      id: `stage:${label}`,
      label,
      text: `[当前学习阶段] ${label}`,
    };
  }
  if (surface === "resources") {
    const resource = context.resourceLabel?.trim();
    if (!resource) {
      return null;
    }
    return {
      id: `resource:${resource}`,
      label: resource,
      text: `[当前资料] ${resource}`,
    };
  }
  return null;
}

/** Join the learner text with the anchor line (anchor last, dedup-safe). */
export function appendDockAnchor(text: string, anchor: DockContextAnchor | null): string {
  const normalized = text.trim();
  if (!anchor) {
    return normalized;
  }
  if (normalized.includes(anchor.text)) {
    return normalized;
  }
  return normalized ? `${normalized}\n\n${anchor.text}` : anchor.text;
}

/**
 * returnToSurface banner copy (§3.7 red line 5, stay mode): shown after the
 * coach answer finishes while the learner remained on Learning/Resources.
 * Eight UI languages, keyed the same way as copy.ts.
 */
const DOCK_RETURN_BANNER_COPY: Record<string, { title: string; action: string; back: string }> = {
  "zh-CN": { title: "教练已回答", action: "去查看", back: "回到学习" },
  "en-US": { title: "Coach replied", action: "View reply", back: "Back to Learning" },
  "es-ES": { title: "El coach respondió", action: "Ver respuesta", back: "Volver al aprendizaje" },
  "fr-FR": { title: "Le coach a répondu", action: "Voir la réponse", back: "Retour à l'apprentissage" },
  "de-DE": { title: "Coach geantwortet", action: "Antwort ansehen", back: "Zurück zum Lernen" },
  "ja-JP": { title: "コーチが回答しました", action: "回答を見る", back: "学習に戻る" },
  "ko-KR": { title: "코치가 답했습니다", action: "답변 보기", back: "학습으로 돌아가기" },
  "pt-BR": { title: "O coach respondeu", action: "Ver resposta", back: "Voltar ao aprendizado" },
};

export function dockReturnBannerCopy(
  language: string,
  surface: ComposerDockSurface,
): { title: string; action: string; back: string } {
  const copy = DOCK_RETURN_BANNER_COPY[language] ?? DOCK_RETURN_BANNER_COPY["en-US"];
  if (surface === "resources") {
    return { ...copy, back: surfaceBackCopy(language) };
  }
  return copy;
}

function surfaceBackCopy(language: string): string {
  const back = DOCK_RETURN_BANNER_COPY[language]?.back;
  if (!back) {
    return DOCK_RETURN_BANNER_COPY["en-US"].back;
  }
  // Resources surfaces say "back to Resources" rather than "back to Learning".
  const table: Record<string, string> = {
    "zh-CN": "回到资料",
    "en-US": "Back to Resources",
    "es-ES": "Volver a los recursos",
    "fr-FR": "Retour aux ressources",
    "de-DE": "Zurück zu den Ressourcen",
    "ja-JP": "資料に戻る",
    "ko-KR": "자료로 돌아가기",
    "pt-BR": "Voltar aos recursos",
  };
  return table[language] ?? table["en-US"];
}

/**
 * Send-preference switch copy (§3.7 red line 5): a visible two-option switch
 * in the dock strip on Learning/Resources. "jump" is the historical default —
 * a send follows the streamed answer into Coach; "stay" keeps the working
 * surface and leans on the returnToSurface bar. Coach never renders it: a
 * send there always stays in the thread.
 */
const DOCK_SEND_PREFERENCE_COPY: Record<string, { label: string; jump: string; stay: string }> = {
  "zh-CN": { label: "发送后", jump: "跳转回答", stay: "留在本页" },
  "en-US": { label: "After send", jump: "Jump to reply", stay: "Stay here" },
  "es-ES": { label: "Tras enviar", jump: "Ir a la respuesta", stay: "Quedarme aquí" },
  "fr-FR": { label: "Après l'envoi", jump: "Aller à la réponse", stay: "Rester ici" },
  "de-DE": { label: "Nach dem Senden", jump: "Zur Antwort", stay: "Hierbleiben" },
  "ja-JP": { label: "送信後", jump: "回答へ移動", stay: "ここに留まる" },
  "ko-KR": { label: "전송 후", jump: "답변으로 이동", stay: "여기 머무르기" },
  "pt-BR": { label: "Após enviar", jump: "Ir para a resposta", stay: "Ficar aqui" },
};

export function dockSendPreferenceCopy(language: string): { label: string; jump: string; stay: string } {
  return DOCK_SEND_PREFERENCE_COPY[language] ?? DOCK_SEND_PREFERENCE_COPY["en-US"];
}
