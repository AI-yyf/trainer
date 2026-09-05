import { StatusPill } from "../../StatusPill";
import { describeWorkspaceAuthoritySummary } from "../../../../../../shared/src/workspaceAuthority";
import type { ComposerLanguage, WorkspaceAuthority } from "../../../lib/types";

const workspaceAuthoritySummaryCopy: Record<
  ComposerLanguage,
  {
    unconfigured: string;
    unknownSource: string;
    eyebrow: string;
    lede: string;
    root: string;
    source: string;
    ledger: string;
    mountedSources: string;
    trash: string;
    nextSafeMove: string;
  }
> = {
  "zh-CN": {
    unconfigured: "未配置",
    unknownSource: "未知来源",
    eyebrow: "工作区边界",
    lede: "显式打开的工作区根目录，就是读取、修改和整理的边界。",
    root: "根目录",
    source: "来源",
    ledger: "台账 / 检查点",
    mountedSources: "挂载来源",
    trash: "Trash",
    nextSafeMove: "下一步安全动作",
  },
  "en-US": {
    unconfigured: "Unconfigured",
    unknownSource: "Unknown source",
    eyebrow: "Workspace boundary",
    lede: "The explicitly opened workspace root is the boundary for reads, edits, and reorganization.",
    root: "Root",
    source: "Source",
    ledger: "Ledger / checkpoints",
    mountedSources: "Mounted sources",
    trash: "Trash",
    nextSafeMove: "Next safe move",
  },
  "es-ES": {
    unconfigured: "Sin configurar",
    unknownSource: "Origen desconocido",
    eyebrow: "Límite del workspace",
    lede: "La raíz del workspace abierta de forma explícita marca el límite para leer, editar y reorganizar.",
    root: "Raíz",
    source: "Origen",
    ledger: "Registro / checkpoints",
    mountedSources: "Fuentes montadas",
    trash: "Trash",
    nextSafeMove: "Siguiente movimiento seguro",
  },
  "fr-FR": {
    unconfigured: "Non configuré",
    unknownSource: "Source inconnue",
    eyebrow: "Limite du workspace",
    lede: "La racine du workspace ouverte explicitement définit la limite pour lire, modifier et réorganiser.",
    root: "Racine",
    source: "Source",
    ledger: "Journal / checkpoints",
    mountedSources: "Sources montées",
    trash: "Trash",
    nextSafeMove: "Prochain mouvement sûr",
  },
  "de-DE": {
    unconfigured: "Nicht konfiguriert",
    unknownSource: "Unbekannte Quelle",
    eyebrow: "Workspace-Grenze",
    lede: "Der ausdrücklich geöffnete Workspace-Stamm ist die Grenze für Lesen, Bearbeiten und Neuordnen.",
    root: "Wurzelpfad",
    source: "Quelle",
    ledger: "Protokoll / Checkpoints",
    mountedSources: "Eingebundene Quellen",
    trash: "Trash",
    nextSafeMove: "Nächster sicherer Schritt",
  },
  "ja-JP": {
    unconfigured: "未設定",
    unknownSource: "不明なソース",
    eyebrow: "workspace の境界",
    lede: "明示的に開いた workspace ルートが、読み取り・編集・再整理の境界になります。",
    root: "ルート",
    source: "ソース",
    ledger: "台帳 / チェックポイント",
    mountedSources: "マウント元",
    trash: "Trash",
    nextSafeMove: "次の安全な一手",
  },
  "ko-KR": {
    unconfigured: "미설정",
    unknownSource: "알 수 없는 출처",
    eyebrow: "workspace 경계",
    lede: "명시적으로 연 workspace 루트가 읽기, 편집, 재구성의 경계입니다.",
    root: "루트",
    source: "출처",
    ledger: "기록 / 체크포인트",
    mountedSources: "마운트된 소스",
    trash: "Trash",
    nextSafeMove: "다음 안전한 움직임",
  },
  "pt-BR": {
    unconfigured: "Não configurado",
    unknownSource: "Origem desconhecida",
    eyebrow: "Limite do workspace",
    lede: "A raiz do workspace aberta de forma explícita define o limite para leitura, edição e reorganização.",
    root: "Raiz",
    source: "Origem",
    ledger: "Registro / checkpoints",
    mountedSources: "Fontes montadas",
    trash: "Trash",
    nextSafeMove: "Próximo movimento seguro",
  },
};

function summaryCopy(language: ComposerLanguage) {
  return workspaceAuthoritySummaryCopy[language] ?? workspaceAuthoritySummaryCopy["en-US"];
}

export interface WorkspaceAuthoritySummaryProps {
  language: ComposerLanguage;
  authority?: WorkspaceAuthority | null;
  className?: string;
}

export function WorkspaceAuthoritySummary({ language, authority, className }: WorkspaceAuthoritySummaryProps) {
  const summary = describeWorkspaceAuthoritySummary(authority, language);
  if (!authority || !summary.hasWorkspaceRoot) {
    return null;
  }

  const copy = summaryCopy(language);
  const permission = summary.permission || copy.unconfigured;
  const source = summary.source || copy.unknownSource;
  const rootDetail = summary.rootDetail.trim();
  const sourceDetail = summary.sourceDetail.trim();
  const hasSeparateRemoteIdentity = Boolean(
    authority.remoteName?.trim() && authority.authoritySource?.trim() && sourceDetail,
  );
  const mountedSources = summary.mountedSourcesText;
  const trashRoot = summary.trashRoot || copy.unconfigured;

  return (
    <section className={["section-block", "workspace-authority-summary", className].filter(Boolean).join(" ")}>
      <div className="section-block__header workspace-authority-summary__header">
        <div>
          <span className="eyebrow">{copy.eyebrow}</span>
          <p className="workspace-authority-summary__lede">{copy.lede}</p>
        </div>
        <StatusPill tone="connected">{permission}</StatusPill>
      </div>
      <div className="workspace-authority-summary__grid">
        <div className="workspace-authority-summary__item">
          <span>{copy.root}</span>
          <strong title={rootDetail || summary.root}>{summary.root}</strong>
        </div>
        <div className="workspace-authority-summary__item">
          <span>{copy.source}</span>
          <strong title={sourceDetail || source}>{source}</strong>
          {hasSeparateRemoteIdentity ? (
            <span data-workspace-authority-remote title={sourceDetail}>
              {sourceDetail}
            </span>
          ) : null}
        </div>
        <div className="workspace-authority-summary__item">
          <span>{copy.ledger}</span>
          <strong>
            {summary.ledgerEntryCount} / {summary.checkpointCount}
          </strong>
        </div>
        {summary.mountedSourceCount > 0 ? (
          <div className="workspace-authority-summary__item">
            <span>{copy.mountedSources}</span>
            <strong title={summary.mountedSourcesDetail || mountedSources}>{mountedSources}</strong>
          </div>
        ) : null}
        <div className="workspace-authority-summary__item">
          <span>{copy.trash}</span>
          <strong>{trashRoot}</strong>
        </div>
        <div className="workspace-authority-summary__item workspace-authority-summary__item--action">
          <span>{copy.nextSafeMove}</span>
          <strong>{summary.nextSafeAction}</strong>
        </div>
      </div>
    </section>
  );
}
