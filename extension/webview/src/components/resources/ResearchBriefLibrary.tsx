import { useEffect, useRef } from "react";
import { RESEARCH_BRIEF_SECTIONS, type ResearchBriefView } from "../../../../../shared/src/researchBrief";
import type { ComposerLanguage, ResourceRecord } from "../../lib/types";
import { CoachMessageParts } from "../coach/CoachMessageParts";

const COPY: Record<ComposerLanguage, readonly string[]> = {
  "zh-CN": ["备课简报", "研究发现", "原文支持", "推断", "待核实", "备课详情", "第 {n} 页", "第 {n} 张幻灯片", "第 {n} 行", "核心问题", "来源分歧", "关键概念", "前置知识", "知识结构", "教学顺序", "解释策略", "示例", "常见误区", "检查题", "验收标准", "未解决的问题", "后续研究"],
  "en-US": ["Research briefs", "Findings", "Source-backed", "Inference", "Unverified", "Preparation details", "Page {n}", "Slide {n}", "Line {n}", "Key questions", "Source disagreements", "Concepts", "Prerequisites", "Knowledge structure", "Teaching order", "Explanation strategy", "Examples", "Misconceptions", "Check questions", "Acceptance criteria", "Open questions", "Follow-up research"],
  "es-ES": ["Informes de investigación", "Hallazgos", "Respaldado por fuentes", "Inferencia", "Sin verificar", "Preparación", "Página {n}", "Diapositiva {n}", "Línea {n}", "Preguntas clave", "Discrepancias entre fuentes", "Conceptos", "Requisitos previos", "Estructura del conocimiento", "Orden de enseñanza", "Estrategia de explicación", "Ejemplos", "Errores frecuentes", "Preguntas de comprobación", "Criterios de aceptación", "Preguntas abiertas", "Investigación posterior"],
  "fr-FR": ["Notes de recherche", "Résultats", "Étayer par les sources", "Inférence", "Non vérifié", "Préparation", "Page {n}", "Diapositive {n}", "Ligne {n}", "Questions clés", "Divergences entre sources", "Concepts", "Prérequis", "Structure des connaissances", "Ordre pédagogique", "Stratégie d’explication", "Exemples", "Idées reçues", "Questions de contrôle", "Critères d’acceptation", "Questions ouvertes", "Pistes de recherche"],
  "de-DE": ["Rechercheberichte", "Ergebnisse", "Quellenbelegt", "Schlussfolgerung", "Ungeprüft", "Unterrichtsvorbereitung", "Seite {n}", "Folie {n}", "Zeile {n}", "Leitfragen", "Abweichende Quellen", "Konzepte", "Vorkenntnisse", "Wissensstruktur", "Unterrichtsreihenfolge", "Erklärstrategie", "Beispiele", "Fehlvorstellungen", "Kontrollfragen", "Abnahmekriterien", "Offene Fragen", "Weitere Recherche"],
  "ja-JP": ["授業準備の調査メモ", "調査結果", "出典あり", "推論", "未確認", "授業準備の詳細", "{n} ページ", "スライド {n}", "{n} 行目", "主要な問い", "出典間の相違", "概念", "前提知識", "知識の構造", "教える順序", "説明方針", "例", "よくある誤解", "確認問題", "達成基準", "未解決の問い", "追加調査"],
  "ko-KR": ["연구 브리프", "연구 결과", "출처로 확인", "추론", "미확인", "수업 준비 세부 사항", "{n}쪽", "슬라이드 {n}", "{n}행", "핵심 질문", "출처 간 이견", "개념", "선행 지식", "지식 구조", "수업 순서", "설명 전략", "예시", "흔한 오해", "확인 질문", "완료 기준", "미해결 질문", "후속 연구"],
  "pt-BR": ["Relatórios de pesquisa", "Resultados", "Com fonte", "Inferência", "Não verificado", "Preparação", "Página {n}", "Slide {n}", "Linha {n}", "Perguntas-chave", "Divergências entre fontes", "Conceitos", "Pré-requisitos", "Estrutura do conhecimento", "Ordem de ensino", "Estratégia de explicação", "Exemplos", "Equívocos comuns", "Perguntas de verificação", "Critérios de aceitação", "Perguntas em aberto", "Pesquisa adicional"],
};

export function ResearchBriefLibrary({ briefs, language, resources, requestedBrief }: {
  briefs: ResearchBriefView[];
  language: ComposerLanguage;
  resources: ResourceRecord[];
  requestedBrief?: { id: string };
}) {
  const list = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (!requestedBrief || !list.current) return;
    const details = list.current.querySelector<HTMLDetailsElement>(`[data-research-brief-id="${CSS.escape(requestedBrief.id)}"]`);
    if (!details) return;
    list.current.open = true;
    details.open = true;
    details.querySelector("summary")?.focus();
  }, [requestedBrief]);
  const [label, findings, sourced, inferred, unverified, preparation, page, slide, line, ...sectionLabels] = COPY[language];
  const statuses = { sourced, inferred, unverified };
  return (
    <details className="template-disclosure resource-briefs" data-research-briefs ref={list}>
      <summary>{label} <span className="template-metadata">{briefs.length}</span></summary>
      <div className="resource-briefs__list">
        {briefs.map((brief) => (
          <details className="resource-briefs__brief" key={brief.id} data-research-brief-id={brief.id}>
            <summary>{brief.title}</summary>
            <div className="resource-briefs__body">
              {brief.goal && brief.goal !== brief.title ? <p>{brief.goal}</p> : null}
              {brief.findings.length ? <>
                <h3>{findings}</h3>
                <ol className="resource-briefs__findings">
                  {brief.findings.map((finding, index) => (
                    <li key={index} data-brief-claim-status={finding.status}>
                      <span className="template-metadata">{statuses[finding.status]}</span>
                      <p>{finding.statement}</p>
                      {finding.citations.map((citation, citationIndex) => {
                        const location = citation.location;
                        const position = [
                          typeof location?.page === "number" ? page.replace("{n}", String(location.page)) : "",
                          typeof location?.slide === "number" ? slide.replace("{n}", String(location.slide)) : "",
                          typeof location?.heading === "string" ? location.heading : "",
                          typeof location?.line_start === "number" ? line.replace("{n}", String(location.line_start)) : "",
                        ].filter(Boolean).join(" · ");
                        return (
                          <figure key={citationIndex} className="resource-briefs__citation">
                            <blockquote>{citation.snippet}</blockquote>
                            <figcaption>
                              <CoachMessageParts parts={[citation]} language={language} resources={resources} />
                              <span className="template-metadata">{position}</span>
                            </figcaption>
                          </figure>
                        );
                      })}
                    </li>
                  ))}
                </ol>
              </> : null}
              {Object.keys(brief.sections).length ? (
                <details className="template-disclosure">
                  <summary>{preparation}</summary>
                  {RESEARCH_BRIEF_SECTIONS.map((key, index) => {
                    const lines = brief.sections[key];
                    if (!lines?.length) return null;
                    return <section key={key} data-brief-section={key}>
                      <h3>{sectionLabels[index]}</h3>
                      <ul>{lines.map((text, itemIndex) => <li key={itemIndex}>{text}</li>)}</ul>
                    </section>;
                  })}
                </details>
              ) : null}
            </div>
          </details>
        ))}
      </div>
    </details>
  );
}
