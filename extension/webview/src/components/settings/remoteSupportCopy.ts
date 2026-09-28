/**
 * Remote-support settings panel copy (§十五: eight languages, no zh/en
 * binaries in the Remote/SSH surface).
 */
import type { ComposerLanguage } from "../../lib/types";
import type { CompanionInstallState } from "../../../../../shared/src/companionInstallState";

export type RemoteSupportCopy = {
  sectionTitle: string;
  remoteHost: string;
  intro: string;
  states: Record<
    CompanionInstallState,
    { button: string; note?: string; disabled: boolean }
  >;
};

export const REMOTE_SUPPORT_COPY: Record<ComposerLanguage, RemoteSupportCopy> = {
  "zh-CN": {
    sectionTitle: "远程支持",
    remoteHost: "远程环境",
    intro:
      "Trainer 通过 Remote Workspace Companion 读取远端文件、搜索和验证。如果尚未安装，请点击下方按钮。",
    states: {
      not_installed: { button: "安装远程支持", disabled: false },
      installing: {
        button: "正在安装…",
        note: "VS Code 正在安装 Companion。",
        disabled: true,
      },
      await_reload: {
        button: "等待 Reload",
        note: "安装完成，请重载远程窗口后回到这里。",
        disabled: true,
      },
      preparing: { button: "准备中…", disabled: true },
      ready: {
        button: "远程支持已就绪",
        note: "已就绪；可随时重装。",
        disabled: true,
      },
      version_incompatible: {
        button: "版本不兼容，重新安装",
        note: "Companion 与 Trainer 版本不匹配，请重装。",
        disabled: false,
      },
      connection_lost: {
        button: "连接丢失，重新安装",
        note: "远程连接断开。恢复连接后如仍未就绪，请重装。",
        disabled: false,
      },
      upgrade_available: {
        button: "远程支持已就绪",
        note: "有可用更新，可随时重装升级。",
        disabled: true,
      },
    },
  },
  "en-US": {
    sectionTitle: "Remote support",
    remoteHost: "Remote host",
    intro:
      "Trainer uses the Remote Workspace Companion for remote file access, search, and verification. Install it below if not yet available.",
    states: {
      not_installed: { button: "Install Remote Support", disabled: false },
      installing: {
        button: "Installing…",
        note: "VS Code is installing the companion.",
        disabled: true,
      },
      await_reload: {
        button: "Waiting for reload",
        note: "Install finished — reload the remote window, then come back.",
        disabled: true,
      },
      preparing: { button: "Preparing…", disabled: true },
      ready: {
        button: "Remote support ready",
        note: "Ready; reinstall any time.",
        disabled: true,
      },
      version_incompatible: {
        button: "Version mismatch — reinstall",
        note: "The companion version does not match Trainer. Reinstall it.",
        disabled: false,
      },
      connection_lost: {
        button: "Connection lost — reinstall",
        note: "The remote connection dropped. Reinstall if it is still not ready after reconnecting.",
        disabled: false,
      },
      upgrade_available: {
        button: "Remote support ready",
        note: "An update is available; reinstall any time.",
        disabled: true,
      },
    },
  },
  "es-ES": {
    sectionTitle: "Soporte remoto",
    remoteHost: "Entorno remoto",
    intro:
      "Trainer usa el Remote Workspace Companion para acceder a archivos remotos, buscar y verificar. Instálalo abajo si aún no está.",
    states: {
      not_installed: { button: "Instalar soporte remoto", disabled: false },
      installing: {
        button: "Instalando…",
        note: "VS Code está instalando el companion.",
        disabled: true,
      },
      await_reload: {
        button: "Esperando recarga",
        note: "Instalación terminada: recarga la ventana remota y vuelve.",
        disabled: true,
      },
      preparing: { button: "Preparando…", disabled: true },
      ready: {
        button: "Soporte remoto listo",
        note: "Listo; reinstala cuando quieras.",
        disabled: true,
      },
      version_incompatible: {
        button: "Versión incompatible — reinstalar",
        note: "La versión del companion no coincide con Trainer. Reinstálalo.",
        disabled: false,
      },
      connection_lost: {
        button: "Conexión perdida — reinstalar",
        note: "Se perdió la conexión remota. Reinstala si sigue sin estar listo tras reconectar.",
        disabled: false,
      },
      upgrade_available: {
        button: "Soporte remoto listo",
        note: "Hay una actualización disponible; reinstala cuando quieras.",
        disabled: true,
      },
    },
  },
  "fr-FR": {
    sectionTitle: "Support distant",
    remoteHost: "Hôte distant",
    intro:
      "Trainer utilise le Remote Workspace Companion pour l'accès aux fichiers distants, la recherche et la vérification. Installez-le ci-dessous s'il n'est pas encore présent.",
    states: {
      not_installed: { button: "Installer le support distant", disabled: false },
      installing: {
        button: "Installation…",
        note: "VS Code installe le companion.",
        disabled: true,
      },
      await_reload: {
        button: "En attente de rechargement",
        note: "Installation terminée : rechargez la fenêtre distante puis revenez.",
        disabled: true,
      },
      preparing: { button: "Préparation…", disabled: true },
      ready: {
        button: "Support distant prêt",
        note: "Prêt ; réinstallez à tout moment.",
        disabled: true,
      },
      version_incompatible: {
        button: "Version incompatible — réinstaller",
        note: "La version du companion ne correspond pas à Trainer. Réinstallez-le.",
        disabled: false,
      },
      connection_lost: {
        button: "Connexion perdue — réinstaller",
        note: "La connexion distante a été perdue. Réinstallez si ce n'est toujours pas prêt après reconnexion.",
        disabled: false,
      },
      upgrade_available: {
        button: "Support distant prêt",
        note: "Une mise à jour est disponible ; réinstallez à tout moment.",
        disabled: true,
      },
    },
  },
  "de-DE": {
    sectionTitle: "Remote-Unterstützung",
    remoteHost: "Remote-Host",
    intro:
      "Trainer nutzt den Remote Workspace Companion für Remote-Dateizugriff, Suche und Verifizierung. Falls noch nicht vorhanden, unten installieren.",
    states: {
      not_installed: { button: "Remote-Unterstützung installieren", disabled: false },
      installing: {
        button: "Wird installiert…",
        note: "VS Code installiert den Companion.",
        disabled: true,
      },
      await_reload: {
        button: "Warten auf Neuladen",
        note: "Installation abgeschlossen — lade das Remote-Fenster neu und komm zurück.",
        disabled: true,
      },
      preparing: { button: "Wird vorbereitet…", disabled: true },
      ready: {
        button: "Remote-Unterstützung bereit",
        note: "Bereit; jederzeit neu installierbar.",
        disabled: true,
      },
      version_incompatible: {
        button: "Version inkompatibel — neu installieren",
        note: "Die Companion-Version passt nicht zu Trainer. Neu installieren.",
        disabled: false,
      },
      connection_lost: {
        button: "Verbindung verloren — neu installieren",
        note: "Die Remote-Verbindung wurde getrennt. Neu installieren, falls danach nicht bereit.",
        disabled: false,
      },
      upgrade_available: {
        button: "Remote-Unterstützung bereit",
        note: "Ein Update ist verfügbar; jederzeit neu installierbar.",
        disabled: true,
      },
    },
  },
  "ja-JP": {
    sectionTitle: "リモートサポート",
    remoteHost: "リモート環境",
    intro:
      "Trainer は Remote Workspace Companion でリモートファイルの読み取り・検索・検証を行います。未インストールなら下のボタンから。",
    states: {
      not_installed: { button: "リモートサポートをインストール", disabled: false },
      installing: {
        button: "インストール中…",
        note: "VS Code が companion をインストールしています。",
        disabled: true,
      },
      await_reload: {
        button: "リロード待ち",
        note: "インストール完了 — リモートウィンドウを再読み込みして戻ってきてください。",
        disabled: true,
      },
      preparing: { button: "準備中…", disabled: true },
      ready: {
        button: "リモートサポート準備完了",
        note: "準備完了。いつでも再インストールできます。",
        disabled: true,
      },
      version_incompatible: {
        button: "バージョン不一致 — 再インストール",
        note: "companion のバージョンが Trainer と一致しません。再インストールしてください。",
        disabled: false,
      },
      connection_lost: {
        button: "接続切断 — 再インストール",
        note: "リモート接続が切断されました。再接続後も準備できていなければ再インストールしてください。",
        disabled: false,
      },
      upgrade_available: {
        button: "リモートサポート準備完了",
        note: "更新があります。いつでも再インストールできます。",
        disabled: true,
      },
    },
  },
  "ko-KR": {
    sectionTitle: "원격 지원",
    remoteHost: "원격 환경",
    intro:
      "Trainer는 Remote Workspace Companion으로 원격 파일 접근, 검색, 검증을 수행합니다. 아직 없다면 아래 버튼에서 설치하세요.",
    states: {
      not_installed: { button: "원격 지원 설치", disabled: false },
      installing: {
        button: "설치 중…",
        note: "VS Code가 companion을 설치하고 있습니다.",
        disabled: true,
      },
      await_reload: {
        button: "새로고침 대기",
        note: "설치 완료 — 원격 창을 다시 불러온 뒤 돌아오세요.",
        disabled: true,
      },
      preparing: { button: "준비 중…", disabled: true },
      ready: {
        button: "원격 지원 준비 완료",
        note: "준비 완료. 언제든 재설치할 수 있습니다.",
        disabled: true,
      },
      version_incompatible: {
        button: "버전 불일치 — 재설치",
        note: "companion 버전이 Trainer와 일치하지 않습니다. 재설치하세요.",
        disabled: false,
      },
      connection_lost: {
        button: "연결 끊김 — 재설치",
        note: "원격 연결이 끊겼습니다. 재연결 후에도 준비되지 않으면 재설치하세요.",
        disabled: false,
      },
      upgrade_available: {
        button: "원격 지원 준비 완료",
        note: "업데이트가 있습니다. 언제든 재설치할 수 있습니다.",
        disabled: true,
      },
    },
  },
  "pt-BR": {
    sectionTitle: "Suporte remoto",
    remoteHost: "Ambiente remoto",
    intro:
      "O Trainer usa o Remote Workspace Companion para acesso a arquivos remotos, busca e verificação. Instale abaixo se ainda não estiver.",
    states: {
      not_installed: { button: "Instalar suporte remoto", disabled: false },
      installing: {
        button: "Instalando…",
        note: "O VS Code está instalando o companion.",
        disabled: true,
      },
      await_reload: {
        button: "Aguardando recarga",
        note: "Instalação concluída — recarregue a janela remota e volte.",
        disabled: true,
      },
      preparing: { button: "Preparando…", disabled: true },
      ready: {
        button: "Suporte remoto pronto",
        note: "Pronto; reinstale quando quiser.",
        disabled: true,
      },
      version_incompatible: {
        button: "Versão incompatível — reinstalar",
        note: "A versão do companion não corresponde ao Trainer. Reinstale.",
        disabled: false,
      },
      connection_lost: {
        button: "Conexão perdida — reinstalar",
        note: "A conexão remota caiu. Reinstale se ainda não estiver pronto após reconectar.",
        disabled: false,
      },
      upgrade_available: {
        button: "Suporte remoto pronto",
        note: "Há uma atualização disponível; reinstale quando quiser.",
        disabled: true,
      },
    },
  },
};

/** Per-state SSH host line shown under the ready button. */
export function remoteSupportStateView(
  language: ComposerLanguage,
  state: CompanionInstallState | undefined,
): { button: string; note?: string; disabled: boolean } {
  const copy = REMOTE_SUPPORT_COPY[language];
  return copy.states[state ?? "not_installed"] ?? copy.states.not_installed;
}
