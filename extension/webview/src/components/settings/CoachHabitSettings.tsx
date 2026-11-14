import { useState } from "react";
import type { CoachHabit, CoachHabitChange } from "../../../../../shared/src/coachHabit";
import type { ComposerLanguage } from "../../lib/types";

const labels: Record<ComposerLanguage, readonly [string, string, string, string, string, string]> = {
  "zh-CN": ["教练记得的习惯", "例如：先举例，再讲公式", "保存", "启用", "停用", "忘记"],
  "en-US": ["Remembered coaching preference", "For example, use examples before formulas", "Save", "Enable", "Disable", "Forget"],
  "es-ES": ["Preferencia de enseñanza", "Por ejemplo, usar ejemplos antes de fórmulas", "Guardar", "Activar", "Desactivar", "Olvidar"],
  "fr-FR": ["Préférence pédagogique mémorisée", "Par exemple, donner un exemple avant la formule", "Enregistrer", "Activer", "Désactiver", "Oublier"],
  "de-DE": ["Gespeicherte Lernpräferenz", "Zum Beispiel zuerst ein Beispiel, dann die Formel", "Speichern", "Aktivieren", "Deaktivieren", "Vergessen"],
  "ja-JP": ["記憶した指導の好み", "例：数式の前に具体例を示す", "保存", "有効にする", "無効にする", "忘れる"],
  "ko-KR": ["기억된 코칭 선호", "예: 공식 전에 예시를 먼저 보여 주세요", "저장", "활성화", "비활성화", "지우기"],
  "pt-BR": ["Preferência de ensino memorizada", "Por exemplo, usar exemplos antes de fórmulas", "Salvar", "Ativar", "Desativar", "Esquecer"],
};

export function CoachHabitSettings({
  language, habit, onChange, saving,
}: {
  language: ComposerLanguage;
  habit: CoachHabit | null;
  onChange: (change: CoachHabitChange) => void;
  saving: boolean;
}) {
  const [draft, setDraft] = useState(habit?.text ?? "");
  const [label, placeholder, save, enable, disable, forget] = labels[language];
  const text = draft.trim();
  return (
    <form
      className="settings-subsection settings-coach-habit"
      onSubmit={(event) => {
        event.preventDefault();
        if (text && text !== habit?.text && !saving) onChange({ action: "save", text });
      }}
    >
      <label className="eyebrow settings-subsection__title" htmlFor="settings-coach-habit">{label}</label>
      <input
        id="settings-coach-habit"
        type="text"
        value={draft}
        placeholder={placeholder}
        maxLength={240}
        disabled={saving}
        onChange={(event) => setDraft(event.target.value)}
      />
      <div className="settings-coach-habit__actions">
        <button className="button button--ghost button--compact" type="submit" disabled={saving || !text || text === habit?.text}>
          {save}
        </button>
        {habit ? (
          <>
            <button className="button button--ghost button--compact" type="button" disabled={saving}
              onClick={() => onChange({ action: habit.enabled ? "disable" : "enable" })}>
              {habit.enabled ? disable : enable}
            </button>
            <button className="button button--ghost button--compact" type="button" disabled={saving}
              onClick={() => onChange({ action: "forget" })}>
              {forget}
            </button>
          </>
        ) : null}
      </div>
    </form>
  );
}
