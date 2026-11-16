import type { ResourceVersionCheckResult } from "../../../../../shared/src/models";
import type { ComposerLanguage } from "../../../../../shared/src/types";

type Status = ResourceVersionCheckResult["status"];
type Basis = NonNullable<ResourceVersionCheckResult["basis"]>;
type VersionCopy = {
  title: string;
  checking: string;
  empty: string;
  interrupted: string;
  close: string;
  status: Record<Status, string>;
  basis: Record<Basis, string>;
};

export const resourceVersionCopy: Record<ComposerLanguage, VersionCopy> = {
  "zh-CN": {
    title: "源站版本核对", checking: "正在核对源站", empty: "资料库里还没有可核对的资料。",
    interrupted: "核对中断，请重试。", close: "关闭",
    status: {
      unchanged: "与已保存版本一致", changed: "源站内容已变化",
      no_source: "没有在线来源", no_baseline: "没有可比较的完整快照",
      network_disabled: "网络获取已关闭", fetch_failed: "暂时无法核对源站",
      stale: "资料版本已变动，请重新核对", missing: "资料已移出当前资料库",
    },
    basis: { page: "网页正文", pdf: "PDF 文件", repository: "已采集的仓库文档", indexed_url: "已索引的网页内容" },
  },
  "en-US": {
    title: "Source version check", checking: "Checking sources", empty: "The library has no resources to check.",
    interrupted: "The check was interrupted. Try again.", close: "Close",
    status: {
      unchanged: "Matches the saved version", changed: "Source content has changed",
      no_source: "No online source", no_baseline: "No complete snapshot to compare",
      network_disabled: "Network fetching is off", fetch_failed: "Could not check the source",
      stale: "The saved version changed. Check again.", missing: "Resource is no longer in this library",
    },
    basis: { page: "Page content", pdf: "PDF file", repository: "Captured repository documentation", indexed_url: "Indexed page content" },
  },
  "es-ES": {
    title: "Comprobación de versiones", checking: "Comprobando las fuentes", empty: "No hay recursos que comprobar.",
    interrupted: "Se interrumpió la comprobación. Inténtalo de nuevo.", close: "Cerrar",
    status: {
      unchanged: "Coincide con la versión guardada", changed: "El contenido de origen cambió",
      no_source: "Sin fuente en línea", no_baseline: "Sin copia completa para comparar",
      network_disabled: "El acceso a la red está desactivado", fetch_failed: "No se pudo comprobar la fuente",
      stale: "La versión guardada cambió. Compruébala de nuevo.", missing: "El recurso ya no está en la biblioteca",
    },
    basis: { page: "Contenido de la página", pdf: "Archivo PDF", repository: "Documentación del repositorio guardada", indexed_url: "Contenido indexado" },
  },
  "fr-FR": {
    title: "Vérification des versions", checking: "Vérification des sources", empty: "Aucune ressource à vérifier.",
    interrupted: "La vérification a été interrompue. Réessayez.", close: "Fermer",
    status: {
      unchanged: "Identique à la version enregistrée", changed: "Le contenu de la source a changé",
      no_source: "Aucune source en ligne", no_baseline: "Aucune copie complète à comparer",
      network_disabled: "L’accès au réseau est désactivé", fetch_failed: "Impossible de vérifier la source",
      stale: "La version enregistrée a changé. Vérifiez de nouveau.", missing: "La ressource a quitté la bibliothèque",
    },
    basis: { page: "Contenu de la page", pdf: "Fichier PDF", repository: "Documentation du dépôt enregistrée", indexed_url: "Contenu indexé" },
  },
  "de-DE": {
    title: "Quellversionen prüfen", checking: "Quellen werden geprüft", empty: "Keine Ressourcen zum Prüfen vorhanden.",
    interrupted: "Die Prüfung wurde unterbrochen. Versuche es erneut.", close: "Schließen",
    status: {
      unchanged: "Entspricht der gespeicherten Version", changed: "Der Quellinhalt hat sich geändert",
      no_source: "Keine Onlinequelle", no_baseline: "Keine vollständige Kopie zum Vergleich",
      network_disabled: "Der Netzwerkabruf ist deaktiviert", fetch_failed: "Die Quelle konnte nicht geprüft werden",
      stale: "Die gespeicherte Version hat sich geändert. Prüfe erneut.", missing: "Die Ressource ist nicht mehr in der Bibliothek",
    },
    basis: { page: "Seiteninhalt", pdf: "PDF-Datei", repository: "Gespeicherte Repository-Dokumentation", indexed_url: "Indexierter Seiteninhalt" },
  },
  "ja-JP": {
    title: "配信元のバージョン確認", checking: "配信元を確認中", empty: "確認できる資料がありません。",
    interrupted: "確認が中断されました。もう一度お試しください。", close: "閉じる",
    status: {
      unchanged: "保存済みの版と一致", changed: "配信元の内容が変更されました",
      no_source: "オンラインの配信元なし", no_baseline: "比較用の完全なスナップショットなし",
      network_disabled: "ネットワーク取得は無効です", fetch_failed: "配信元を確認できませんでした",
      stale: "保存済みの版が変わりました。再確認してください。", missing: "ライブラリに資料がありません",
    },
    basis: { page: "ページ本文", pdf: "PDF ファイル", repository: "保存したリポジトリのドキュメント", indexed_url: "インデックス済みのページ本文" },
  },
  "ko-KR": {
    title: "원본 버전 확인", checking: "원본 확인 중", empty: "확인할 자료가 없습니다.",
    interrupted: "확인이 중단되었습니다. 다시 시도하세요.", close: "닫기",
    status: {
      unchanged: "저장한 버전과 일치", changed: "원본 내용이 변경됨",
      no_source: "온라인 출처 없음", no_baseline: "비교할 전체 스냅샷 없음",
      network_disabled: "네트워크 가져오기가 꺼져 있음", fetch_failed: "원본을 확인할 수 없음",
      stale: "저장된 버전이 바뀌었습니다. 다시 확인하세요.", missing: "자료가 라이브러리에서 제거됨",
    },
    basis: { page: "페이지 본문", pdf: "PDF 파일", repository: "저장한 저장소 문서", indexed_url: "색인된 페이지 내용" },
  },
  "pt-BR": {
    title: "Verificação de versões", checking: "Verificando as fontes", empty: "Não há recursos para verificar.",
    interrupted: "A verificação foi interrompida. Tente novamente.", close: "Fechar",
    status: {
      unchanged: "Corresponde à versão salva", changed: "O conteúdo da fonte mudou",
      no_source: "Sem fonte on-line", no_baseline: "Sem cópia completa para comparar",
      network_disabled: "O acesso à rede está desativado", fetch_failed: "Não foi possível verificar a fonte",
      stale: "A versão salva mudou. Verifique novamente.", missing: "O recurso saiu da biblioteca",
    },
    basis: { page: "Conteúdo da página", pdf: "Arquivo PDF", repository: "Documentação do repositório salva", indexed_url: "Conteúdo indexado" },
  },
};
