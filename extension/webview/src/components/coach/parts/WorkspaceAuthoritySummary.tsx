import { StatusPill } from "../../StatusPill";
import { describeWorkspaceAuthoritySummary } from "../../../../../../shared/src/workspaceAuthority";
import type { ComposerLanguage, WorkspaceAuthority } from "../../../lib/types";
import { workspaceAuthoritySummaryCopy } from "../../../lib/i18n/segments/coachInlineText";


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
