import { useCallback, useId, useState } from "react";
import type { ComposerLanguage, FirstLookSummary } from "../../lib/types";
import { useTranslation } from "../../lib/i18n/useTranslation";

interface FirstLookSummaryPanelProps {
  summary: FirstLookSummary;
  compact?: boolean;
}

type FirstLookLabels = {
  folderRoles: Record<FirstLookSummary["folderRole"], string>;
  projectTypes: Record<FirstLookSummary["projectTypeGuess"], string>;
};

const FIRST_LOOK_LABELS: Record<ComposerLanguage, FirstLookLabels> = {
  "zh-CN": {
    folderRoles: {
      empty_new_project: "新建项目",
      existing_engineering: "现有工程项目",
      algorithm_model: "算法或模型项目",
      idea_scratchpad: "想法草稿",
      learning_materials: "学习资料",
      mixed_uncertain: "用途待确认",
    },
    projectTypes: {
      web_app: "Web 应用",
      api_service: "API 服务",
      cli_tool: "命令行工具",
      library_package: "库或软件包",
      ml_model: "机器学习模型",
      notebook_research: "研究笔记本",
      mobile_app: "移动应用",
      desktop_app: "桌面应用",
      embedded_iot: "嵌入式或物联网项目",
      data_pipeline: "数据管道",
      monorepo: "单体仓库",
      documentation: "文档项目",
      game: "游戏项目",
      config_dotfiles: "配置文件",
      unknown: "未确认",
    },
  },
  "en-US": {
    folderRoles: {
      empty_new_project: "New project",
      existing_engineering: "Existing engineering project",
      algorithm_model: "Algorithm or model project",
      idea_scratchpad: "Idea scratchpad",
      learning_materials: "Learning materials",
      mixed_uncertain: "Purpose not yet clear",
    },
    projectTypes: {
      web_app: "Web app",
      api_service: "API service",
      cli_tool: "Command-line tool",
      library_package: "Library or package",
      ml_model: "Machine learning model",
      notebook_research: "Research notebook",
      mobile_app: "Mobile app",
      desktop_app: "Desktop app",
      embedded_iot: "Embedded or IoT project",
      data_pipeline: "Data pipeline",
      monorepo: "Monorepo",
      documentation: "Documentation project",
      game: "Game project",
      config_dotfiles: "Configuration files",
      unknown: "Unknown",
    },
  },
  "es-ES": {
    folderRoles: {
      empty_new_project: "Proyecto nuevo",
      existing_engineering: "Proyecto de ingeniería existente",
      algorithm_model: "Proyecto de algoritmo o modelo",
      idea_scratchpad: "Borrador de ideas",
      learning_materials: "Materiales de aprendizaje",
      mixed_uncertain: "Propósito aún no claro",
    },
    projectTypes: {
      web_app: "Aplicación web",
      api_service: "Servicio API",
      cli_tool: "Herramienta de línea de comandos",
      library_package: "Biblioteca o paquete",
      ml_model: "Modelo de aprendizaje automático",
      notebook_research: "Cuaderno de investigación",
      mobile_app: "Aplicación móvil",
      desktop_app: "Aplicación de escritorio",
      embedded_iot: "Proyecto integrado o de IoT",
      data_pipeline: "Canalización de datos",
      monorepo: "Monorepo",
      documentation: "Proyecto de documentación",
      game: "Proyecto de juego",
      config_dotfiles: "Archivos de configuración",
      unknown: "Desconocido",
    },
  },
  "fr-FR": {
    folderRoles: {
      empty_new_project: "Nouveau projet",
      existing_engineering: "Projet d'ingénierie existant",
      algorithm_model: "Projet d'algorithme ou de modèle",
      idea_scratchpad: "Brouillon d'idées",
      learning_materials: "Supports d'apprentissage",
      mixed_uncertain: "Objectif encore incertain",
    },
    projectTypes: {
      web_app: "Application web",
      api_service: "Service API",
      cli_tool: "Outil en ligne de commande",
      library_package: "Bibliothèque ou package",
      ml_model: "Modèle d'apprentissage automatique",
      notebook_research: "Carnet de recherche",
      mobile_app: "Application mobile",
      desktop_app: "Application de bureau",
      embedded_iot: "Projet embarqué ou IoT",
      data_pipeline: "Pipeline de données",
      monorepo: "Monorepo",
      documentation: "Projet de documentation",
      game: "Projet de jeu",
      config_dotfiles: "Fichiers de configuration",
      unknown: "Inconnu",
    },
  },
  "de-DE": {
    folderRoles: {
      empty_new_project: "Neues Projekt",
      existing_engineering: "Bestehendes Engineering-Projekt",
      algorithm_model: "Algorithmus- oder Modellprojekt",
      idea_scratchpad: "Ideensammlung",
      learning_materials: "Lernmaterialien",
      mixed_uncertain: "Zweck noch unklar",
    },
    projectTypes: {
      web_app: "Web-App",
      api_service: "API-Dienst",
      cli_tool: "Kommandozeilenwerkzeug",
      library_package: "Bibliothek oder Paket",
      ml_model: "Modell für maschinelles Lernen",
      notebook_research: "Forschungsnotizbuch",
      mobile_app: "Mobile App",
      desktop_app: "Desktop-App",
      embedded_iot: "Embedded- oder IoT-Projekt",
      data_pipeline: "Datenpipeline",
      monorepo: "Monorepo",
      documentation: "Dokumentationsprojekt",
      game: "Spieleprojekt",
      config_dotfiles: "Konfigurationsdateien",
      unknown: "Unbekannt",
    },
  },
  "ja-JP": {
    folderRoles: {
      empty_new_project: "新しいプロジェクト",
      existing_engineering: "既存の開発プロジェクト",
      algorithm_model: "アルゴリズムまたはモデルのプロジェクト",
      idea_scratchpad: "アイデアの下書き",
      learning_materials: "学習資料",
      mixed_uncertain: "用途は未確認",
    },
    projectTypes: {
      web_app: "Web アプリ",
      api_service: "API サービス",
      cli_tool: "コマンドラインツール",
      library_package: "ライブラリまたはパッケージ",
      ml_model: "機械学習モデル",
      notebook_research: "研究ノートブック",
      mobile_app: "モバイルアプリ",
      desktop_app: "デスクトップアプリ",
      embedded_iot: "組み込みまたは IoT プロジェクト",
      data_pipeline: "データパイプライン",
      monorepo: "モノレポ",
      documentation: "ドキュメントプロジェクト",
      game: "ゲームプロジェクト",
      config_dotfiles: "設定ファイル",
      unknown: "不明",
    },
  },
  "ko-KR": {
    folderRoles: {
      empty_new_project: "새 프로젝트",
      existing_engineering: "기존 엔지니어링 프로젝트",
      algorithm_model: "알고리즘 또는 모델 프로젝트",
      idea_scratchpad: "아이디어 초안",
      learning_materials: "학습 자료",
      mixed_uncertain: "용도 미확인",
    },
    projectTypes: {
      web_app: "웹 앱",
      api_service: "API 서비스",
      cli_tool: "명령줄 도구",
      library_package: "라이브러리 또는 패키지",
      ml_model: "머신러닝 모델",
      notebook_research: "연구 노트북",
      mobile_app: "모바일 앱",
      desktop_app: "데스크톱 앱",
      embedded_iot: "임베디드 또는 IoT 프로젝트",
      data_pipeline: "데이터 파이프라인",
      monorepo: "모노레포",
      documentation: "문서 프로젝트",
      game: "게임 프로젝트",
      config_dotfiles: "구성 파일",
      unknown: "알 수 없음",
    },
  },
  "pt-BR": {
    folderRoles: {
      empty_new_project: "Novo projeto",
      existing_engineering: "Projeto de engenharia existente",
      algorithm_model: "Projeto de algoritmo ou modelo",
      idea_scratchpad: "Rascunho de ideias",
      learning_materials: "Materiais de aprendizagem",
      mixed_uncertain: "Finalidade ainda incerta",
    },
    projectTypes: {
      web_app: "Aplicativo web",
      api_service: "Serviço de API",
      cli_tool: "Ferramenta de linha de comando",
      library_package: "Biblioteca ou pacote",
      ml_model: "Modelo de aprendizado de máquina",
      notebook_research: "Notebook de pesquisa",
      mobile_app: "Aplicativo móvel",
      desktop_app: "Aplicativo de desktop",
      embedded_iot: "Projeto embarcado ou IoT",
      data_pipeline: "Pipeline de dados",
      monorepo: "Monorepo",
      documentation: "Projeto de documentação",
      game: "Projeto de jogo",
      config_dotfiles: "Arquivos de configuração",
      unknown: "Desconhecido",
    },
  },
};

function humanizeUnknownClassification(value: string, fallback: string): string {
  const readable = value
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ");
  return readable || fallback;
}

export function FirstLookSummaryPanel({ summary, compact = false }: FirstLookSummaryPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const bodyId = useId();
  const toggle = useCallback(() => setExpanded((v) => !v), []);
  const { t, language } = useTranslation();

  const confidencePercent = Math.round((summary.confidence ?? 0) * 100);
  const labels = FIRST_LOOK_LABELS[language] ?? FIRST_LOOK_LABELS["en-US"];
  const unknownProjectType = labels.projectTypes.unknown;
  const projectTypeText =
    labels.projectTypes[summary.projectTypeGuess] ??
    humanizeUnknownClassification(summary.projectTypeGuess, unknownProjectType);
  const folderRoleText =
    labels.folderRoles[summary.folderRole] ??
    humanizeUnknownClassification(summary.folderRole, unknownProjectType);

  const hasBodyData =
    Boolean(summary.folderRole) ||
    Boolean(summary.whyThisGuess) ||
    (summary.entryPoints && summary.entryPoints.length > 0) ||
    (summary.directoryAnchors && summary.directoryAnchors.length > 0) ||
    (summary.coreModulesOrMaterials && summary.coreModulesOrMaterials.length > 0) ||
    (summary.riskZones && summary.riskZones.length > 0) ||
    (summary.trainingOpportunities && summary.trainingOpportunities.length > 0) ||
    (summary.unknowns && summary.unknowns.length > 0) ||
    Boolean(summary.recommendedNextStep);

  const panelClassName = [
    "firstlook-panel",
    "firstlook-panel--coach-insight",
    compact ? "firstlook-panel--compact" : null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={panelClassName}>
      {!compact ? (
        <div className="firstlook-panel__coach-badge">
          <span className="firstlook-panel__coach-icon" aria-hidden="true">FL</span>
          <span className="firstlook-panel__coach-label">{t("firstLookBadge")}</span>
        </div>
      ) : null}
      {summary.recommendedNextStep ? (
        <div className="firstlook-panel__next-step">
          <span className="firstlook-panel__row-label">{t("firstLookNextStep")}</span>
          <span className="firstlook-panel__row-value firstlook-panel__row-value--accent">
            {summary.recommendedNextStep}
          </span>
        </div>
      ) : null}
      <button
        type="button"
        className="firstlook-panel__header firstlook-panel__header--actionable"
        onClick={toggle}
        aria-expanded={expanded}
        aria-controls={bodyId}
        disabled={!hasBodyData}
      >
        <span className="firstlook-panel__lead">
          {compact ? <span className="firstlook-panel__context">{t("firstLookBadge")}</span> : null}
          <span className="firstlook-panel__label">{t("firstLookProjectType")}:</span>{" "}
          <span className="firstlook-panel__value">{projectTypeText}</span>
          <span className="firstlook-panel__confidence">
            {" "}({confidencePercent}%)
          </span>
        </span>
        {hasBodyData ? (
          <span
            className={`firstlook-panel__chevron ${expanded ? "firstlook-panel__chevron--up" : ""}`}
            aria-hidden="true"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path
                d={expanded ? "M2 8L6 4L10 8" : "M2 4L6 8L10 4"}
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
        ) : null}
      </button>

      {expanded && hasBodyData ? (
        <div id={bodyId} className="firstlook-panel__body">
          {summary.folderRole ? (
            <div className="firstlook-panel__row">
              <span className="firstlook-panel__row-label">{t("firstLookFolderRole")}</span>
              <span className="firstlook-panel__row-value">{folderRoleText}</span>
            </div>
          ) : null}

          {summary.whyThisGuess ? (
            <div className="firstlook-panel__row">
              <span className="firstlook-panel__row-label">{t("firstLookWhyGuess")}</span>
              <span className="firstlook-panel__row-value">{summary.whyThisGuess}</span>
            </div>
          ) : null}

          {summary.entryPoints && summary.entryPoints.length > 0 ? (
            <div className="firstlook-panel__row">
              <span className="firstlook-panel__row-label">{t("firstLookEntryPoints")}</span>
              <span className="firstlook-panel__row-value">
                {summary.entryPoints.join(", ")}
              </span>
            </div>
          ) : null}

          {summary.directoryAnchors && summary.directoryAnchors.length > 0 ? (
            <div className="firstlook-panel__row">
              <span className="firstlook-panel__row-label">{t("firstLookDirectoryAnchors")}</span>
              <span className="firstlook-panel__row-value">
                {summary.directoryAnchors.join(", ")}
              </span>
            </div>
          ) : null}

          {summary.coreModulesOrMaterials && summary.coreModulesOrMaterials.length > 0 ? (
            <div className="firstlook-panel__row">
              <span className="firstlook-panel__row-label">{t("firstLookCoreModules")}</span>
              <span className="firstlook-panel__row-value">
                {summary.coreModulesOrMaterials.join(", ")}
              </span>
            </div>
          ) : null}

          {summary.riskZones && summary.riskZones.length > 0 ? (
            <div className="firstlook-panel__row">
              <span className="firstlook-panel__row-label">{t("firstLookRiskZones")}</span>
              <ul className="firstlook-panel__list firstlook-panel__list--risk">
                {summary.riskZones.map((item, i) => (
                  <li key={i} className="firstlook-panel__list-item firstlook-panel__list-item--risk">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {summary.trainingOpportunities && summary.trainingOpportunities.length > 0 ? (
            <div className="firstlook-panel__row">
              <span className="firstlook-panel__row-label">{t("firstLookOpportunities")}</span>
              <ul className="firstlook-panel__list">
                {summary.trainingOpportunities.map((item, i) => (
                  <li key={i} className="firstlook-panel__list-item firstlook-panel__list-item--opportunity">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {summary.unknowns && summary.unknowns.length > 0 ? (
            <div className="firstlook-panel__row">
              <span className="firstlook-panel__row-label">{t("firstLookUnknowns")}</span>
              <ul className="firstlook-panel__list firstlook-panel__list--unknown">
                {summary.unknowns.map((item, i) => (
                  <li key={i} className="firstlook-panel__list-item firstlook-panel__list-item--unknown">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

        </div>
      ) : null}
    </div>
  );
}
