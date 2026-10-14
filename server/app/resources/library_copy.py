"""User-visible copy for the Trainer Library folder lane, in all eight languages.

The library lane writes real folders inside the opened workspace, so every
refusal it can surface (untrusted workspace, folder escaping the root, download
failure) is shown to the user by the browser extension or the workbench. Those
strings live here, keyed by a stable machine code, with one entry per supported
workspace language — the same eight languages the coach replies and the capture
drafts use. Copy outside the eight known languages falls back to English.
"""

from __future__ import annotations

LIBRARY_COPY: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ root
    "library_root_unavailable": {
        "zh-CN": "Trainer 资料库需要一个本地项目文件夹；当前工作区没有可用的本地根目录。",
        "en-US": "Trainer Library needs an open local project folder; this workspace has no local root.",
        "es-ES": "La Biblioteca de Trainer necesita una carpeta de proyecto local; este espacio de trabajo no tiene raiz local.",
        "fr-FR": "La bibliotheque Trainer a besoin d'un dossier de projet local ; cet espace de travail n'a pas de racine locale.",
        "de-DE": "Die Trainer-Bibliothek braucht einen lokalen Projektordner; dieser Arbeitsbereich hat kein lokales Stammverzeichnis.",
        "ja-JP": "Trainer ライブラリにはローカルのプロジェクトフォルダーが必要です。このワークスペースにはローカルルートがありません。",
        "ko-KR": "Trainer 라이브러리에는 로컬 프로젝트 폴더가 필요합니다. 이 워크스페이스에는 로컬 루트가 없습니다.",
        "pt-BR": "A Biblioteca do Trainer precisa de uma pasta de projeto local; este espaco de trabalho nao tem raiz local.",
    },
    "library_not_writable": {
        "zh-CN": "当前工作区未受信任（或为远程工作区），不能写入 Trainer 资料库。",
        "en-US": "This workspace is not trusted for Trainer Library writes (untrusted or remote workspace).",
        "es-ES": "Este espacio de trabajo no es de confianza para escribir en la Biblioteca de Trainer (sin confianza o remoto).",
        "fr-FR": "Cet espace de travail n'est pas approuve pour ecrire dans la bibliotheque Trainer (non approuve ou distant).",
        "de-DE": "Dieser Arbeitsbereich ist nicht vertrauenswuerdig fuer Schreibzugriffe auf die Trainer-Bibliothek (nicht vertraut oder remote).",
        "ja-JP": "このワークスペースは信頼されていないため（またはリモートのため）、Trainer ライブラリに書き込めません。",
        "ko-KR": "이 워크스페이스는 신뢰되지 않아(또는 원격이어서) Trainer 라이브러리에 쓸 수 없습니다.",
        "pt-BR": "Este espaco de trabalho nao e confiavel para gravacoes na Biblioteca do Trainer (nao confiavel ou remoto).",
    },
    # ---------------------------------------------------------------- targets
    "invalid_target_dir": {
        "zh-CN": "目标文件夹必须是工作区内的相对路径（不能使用绝对路径或“..”）。",
        "en-US": 'The target folder must be a workspace-relative folder path (no absolute paths or "..").',
        "es-ES": "La carpeta de destino debe ser una ruta relativa del espacio de trabajo (sin rutas absolutas ni \"..\").",
        "fr-FR": "Le dossier cible doit etre un chemin relatif a l'espace de travail (pas de chemin absolu ni de \"..\").",
        "de-DE": "Der Zielordner muss ein workspace-relativer Ordnerpfad sein (keine absoluten Pfade, kein \"..\").",
        "ja-JP": "保存先フォルダーはワークスペースからの相対パスである必要があります（絶対パスや「..」は使えません）。",
        "ko-KR": "대상 폴더는 워크스페이스 상대 경로여야 합니다(절대 경로나 \"..\"는 사용할 수 없습니다).",
        "pt-BR": "A pasta de destino deve ser um caminho relativo do espaco de trabalho (sem caminhos absolutos ou \"..\").",
    },
    "target_outside_workspace": {
        "zh-CN": "目标文件夹必须位于工作区根目录内：{target_dir}",
        "en-US": "The target folder must stay inside the workspace root: {target_dir}",
        "es-ES": "La carpeta de destino debe permanecer dentro de la raiz del espacio de trabajo: {target_dir}",
        "fr-FR": "Le dossier cible doit rester dans la racine de l'espace de travail : {target_dir}",
        "de-DE": "Der Zielordner muss innerhalb des Arbeitsbereichs-Stammordners bleiben: {target_dir}",
        "ja-JP": "保存先フォルダーはワークスペースのルート内に置く必要があります：{target_dir}",
        "ko-KR": "대상 폴더는 워크스페이스 루트 안에 있어야 합니다: {target_dir}",
        "pt-BR": "A pasta de destino deve ficar dentro da raiz do espaco de trabalho: {target_dir}",
    },
    "download_network_disabled": {
        "zh-CN": "Trainer 配置已禁用网络抓取，仓库没有下载。",
        "en-US": "Network source acquisition is disabled by Trainer configuration; the repository was not downloaded.",
        "es-ES": "La adquisicion de fuentes por red esta desactivada en la configuracion de Trainer; el repositorio no se descargo.",
        "fr-FR": "L'acquisition par le reseau est desactivee dans la configuration de Trainer ; le depot n'a pas ete telecharge.",
        "de-DE": "Der Netzwerkabruf ist in der Trainer-Konfiguration deaktiviert; das Repository wurde nicht heruntergeladen.",
        "ja-JP": "Trainer の設定でネットワーク取得が無効になっているため、リポジトリはダウンロードされませんでした。",
        "ko-KR": "Trainer 설정에서 네트워크 가져오기가 비활성화되어 저장소를 다운로드하지 않았습니다.",
        "pt-BR": "A aquisicao pela rede esta desativada na configuracao do Trainer; o repositorio nao foi baixado.",
    },
    "download_kind_unsupported": {
        "zh-CN": "只有 PDF 和 GitHub 仓库类型的采集才能保存到文件夹。",
        "en-US": "Only PDF and GitHub repository captures can be saved to a folder.",
        "es-ES": "Solo las capturas de PDF y de repositorios de GitHub pueden guardarse en una carpeta.",
        "fr-FR": "Seules les captures PDF et de depot GitHub peuvent etre enregistrees dans un dossier.",
        "de-DE": "Nur PDF- und GitHub-Repository-Erfassungen koennen in einem Ordner gespeichert werden.",
        "ja-JP": "フォルダーに保存できるのは PDF と GitHub リポジトリのキャプチャだけです。",
        "ko-KR": "폴더에 저장할 수 있는 것은 PDF와 GitHub 저장소 캡처뿐입니다.",
        "pt-BR": "Somente capturas de PDF e de repositorios do GitHub podem ser salvas em uma pasta.",
    },
    "download_source_missing": {
        "zh-CN": "采集到的文件在本地已不可用，因此没有保存到文件夹。",
        "en-US": "The captured file is no longer available locally, so it was not saved to a folder.",
        "es-ES": "El archivo capturado ya no esta disponible localmente, por lo que no se guardo en una carpeta.",
        "fr-FR": "Le fichier capture n'est plus disponible localement ; il n'a pas ete enregistre dans un dossier.",
        "de-DE": "Die erfasste Datei ist lokal nicht mehr verfuegbar und wurde daher nicht in einem Ordner gespeichert.",
        "ja-JP": "取り込んだファイルがローカルで利用できないため、フォルダーに保存されませんでした。",
        "ko-KR": "캡처한 파일을 로컬에서 사용할 수 없어 폴더에 저장하지 않았습니다.",
        "pt-BR": "O arquivo capturado nao esta mais disponivel localmente, entao nao foi salvo em uma pasta.",
    },
    "download_failed": {
        "zh-CN": "Trainer 无法把 {target} 下载到资料库文件夹。",
        "en-US": "Trainer could not download {target} into the library folder.",
        "es-ES": "Trainer no pudo descargar {target} en la carpeta de la biblioteca.",
        "fr-FR": "Trainer n'a pas pu telecharger {target} dans le dossier de la bibliotheque.",
        "de-DE": "Trainer konnte {target} nicht in den Bibliotheksordner herunterladen.",
        "ja-JP": "Trainer は {target} をライブラリフォルダーにダウンロードできませんでした。",
        "ko-KR": "Trainer가 {target}을(를) 라이브러리 폴더에 다운로드하지 못했습니다.",
        "pt-BR": "O Trainer nao conseguiu baixar {target} para a pasta da biblioteca.",
    },
    "library_write_denied": {
        "zh-CN": "当前权限级别不允许这项 Trainer 资料库改动。",
        "en-US": "The current permission level does not allow this Trainer Library change.",
        "es-ES": "El nivel de permiso actual no permite este cambio en la Biblioteca de Trainer.",
        "fr-FR": "Le niveau d'autorisation actuel n'autorise pas cette modification de la bibliotheque Trainer.",
        "de-DE": "Die aktuelle Berechtigungsstufe erlaubt diese Aenderung an der Trainer-Bibliothek nicht.",
        "ja-JP": "現在の権限レベルではこの Trainer ライブラリの変更は許可されていません。",
        "ko-KR": "현재 권한 수준에서는 이 Trainer 라이브러리 변경을 허용하지 않습니다.",
        "pt-BR": "O nivel de permissao atual nao permite esta alteracao na Biblioteca do Trainer.",
    },
    # ----------------------------------------------------------------- groups
    "group_missing_path": {
        "zh-CN": "该请求需要提供文件夹路径。",
        "en-US": "This request needs a library folder path.",
        "es-ES": "Esta solicitud necesita una ruta de carpeta de la biblioteca.",
        "fr-FR": "Cette requete necessite un chemin de dossier de la bibliotheque.",
        "de-DE": "Diese Anfrage braucht einen Bibliotheksordner-Pfad.",
        "ja-JP": "このリクエストにはライブラリフォルダーのパスが必要です。",
        "ko-KR": "이 요청에는 라이브러리 폴더 경로가 필요합니다.",
        "pt-BR": "Esta solicitacao precisa de um caminho de pasta da biblioteca.",
    },
    "group_invalid_path": {
        "zh-CN": "这个资料库文件夹路径无效。",
        "en-US": "That library folder path is not valid.",
        "es-ES": "Esa ruta de carpeta de la biblioteca no es valida.",
        "fr-FR": "Ce chemin de dossier de la bibliotheque n'est pas valide.",
        "de-DE": "Dieser Bibliotheksordner-Pfad ist ungueltig.",
        "ja-JP": "そのライブラリフォルダーのパスは有効ではありません。",
        "ko-KR": "해당 라이브러리 폴더 경로가 올바르지 않습니다.",
        "pt-BR": "Esse caminho de pasta da biblioteca nao e valido.",
    },
    "group_not_found": {
        "zh-CN": "该位置没有资料库文件夹：{path}",
        "en-US": "No library folder exists at: {path}",
        "es-ES": "No existe ninguna carpeta de biblioteca en: {path}",
        "fr-FR": "Aucun dossier de bibliotheque n'existe a : {path}",
        "de-DE": "Unter {path} existiert kein Bibliotheksordner.",
        "ja-JP": "次の場所にライブラリフォルダーはありません：{path}",
        "ko-KR": "다음 위치에 라이브러리 폴더가 없습니다: {path}",
        "pt-BR": "Nao existe pasta da biblioteca em: {path}",
    },
    "group_already_exists": {
        "zh-CN": "该位置已存在资料库文件夹：{path}",
        "en-US": "A library folder already exists at: {path}",
        "es-ES": "Ya existe una carpeta de biblioteca en: {path}",
        "fr-FR": "Un dossier de bibliotheque existe deja a : {path}",
        "de-DE": "Unter {path} existiert bereits ein Bibliotheksordner.",
        "ja-JP": "次の場所にはすでにライブラリフォルダーがあります：{path}",
        "ko-KR": "다음 위치에 이미 라이브러리 폴더가 있습니다: {path}",
        "pt-BR": "Ja existe uma pasta da biblioteca em: {path}",
    },
    "group_is_library_root": {
        "zh-CN": "主 Trainer 资料库文件夹不能被重命名或删除。",
        "en-US": "The main Trainer Library folder cannot be renamed or deleted.",
        "es-ES": "La carpeta principal de la Biblioteca de Trainer no se puede renombrar ni eliminar.",
        "fr-FR": "Le dossier principal de la bibliotheque Trainer ne peut pas etre renomme ni supprime.",
        "de-DE": "Der Hauptordner der Trainer-Bibliothek kann nicht umbenannt oder geloescht werden.",
        "ja-JP": "メインの Trainer ライブラリフォルダーは名前変更も削除もできません。",
        "ko-KR": "기본 Trainer 라이브러리 폴더는 이름을 바꾸거나 삭제할 수 없습니다.",
        "pt-BR": "A pasta principal da Biblioteca do Trainer nao pode ser renomeada nem excluida.",
    },
    "group_rename_into_itself": {
        "zh-CN": "文件夹不能移动到它自己的子文件夹里。",
        "en-US": "A folder cannot be moved into one of its own subfolders.",
        "es-ES": "Una carpeta no puede moverse dentro de una de sus propias subcarpetas.",
        "fr-FR": "Un dossier ne peut pas etre deplace dans l'un de ses propres sous-dossiers.",
        "de-DE": "Ein Ordner kann nicht in einen seiner eigenen Unterordner verschoben werden.",
        "ja-JP": "フォルダーを自身のサブフォルダーに移動することはできません。",
        "ko-KR": "폴더를 자신의 하위 폴더로 옮길 수 없습니다.",
        "pt-BR": "Uma pasta nao pode ser movida para dentro de uma de suas subpastas.",
    },
    "group_mutation_failed": {
        "zh-CN": "资料库文件夹改动没有完成：{path}",
        "en-US": "The library folder change did not complete: {path}",
        "es-ES": "El cambio de la carpeta de la biblioteca no se completo: {path}",
        "fr-FR": "La modification du dossier de la bibliotheque ne s'est pas terminee : {path}",
        "de-DE": "Die Aenderung am Bibliotheksordner wurde nicht abgeschlossen: {path}",
        "ja-JP": "ライブラリフォルダーの変更が完了しませんでした：{path}",
        "ko-KR": "라이브러리 폴더 변경이 완료되지 않았습니다: {path}",
        "pt-BR": "A alteracao da pasta da biblioteca nao foi concluida: {path}",
    },
    # --------------------------------------------------------------- warnings
    "warning_existing_reused": {
        "zh-CN": "已有内容相同的文件，直接复用：{path}",
        "en-US": "A file with identical content already existed; it is reused: {path}",
        "es-ES": "Ya existia un archivo con el mismo contenido; se reutiliza: {path}",
        "fr-FR": "Un fichier au contenu identique existait deja ; il est reutilise : {path}",
        "de-DE": "Eine Datei mit identischem Inhalt war bereits vorhanden; sie wird wiederverwendet: {path}",
        "ja-JP": "同じ内容のファイルがすでにあり、そのまま使用します：{path}",
        "ko-KR": "내용이 같은 파일이 이미 있어 그대로 사용합니다: {path}",
        "pt-BR": "Ja existia um arquivo com o mesmo conteudo; ele foi reutilizado: {path}",
    },
    "warning_collision_renamed": {
        "zh-CN": "{path} 已存在且内容不同，本次保存为 {saved_path}。",
        "en-US": "A different file already existed at {path}; this capture was saved as {saved_path}.",
        "es-ES": "Ya existia otro archivo en {path}; esta captura se guardo como {saved_path}.",
        "fr-FR": "Un autre fichier existait deja a {path} ; cette capture a ete enregistree sous {saved_path}.",
        "de-DE": "Unter {path} existierte bereits eine andere Datei; diese Erfassung wurde als {saved_path} gespeichert.",
        "ja-JP": "{path} には別のファイルがあったため、このキャプチャは {saved_path} として保存しました。",
        "ko-KR": "{path}에 다른 파일이 있어 이 캡처를 {saved_path}(으)로 저장했습니다.",
        "pt-BR": "Ja existia outro arquivo em {path}; esta captura foi salva como {saved_path}.",
    },
    "warning_git_unavailable": {
        "zh-CN": "系统没有可用的 git，已改为下载 ZIP 压缩包。",
        "en-US": "git is not available; the repository was downloaded as a ZIP archive instead.",
        "es-ES": "git no esta disponible; el repositorio se descargo como archivo ZIP.",
        "fr-FR": "git n'est pas disponible ; le depot a ete telecharge sous forme d'archive ZIP.",
        "de-DE": "git ist nicht verfuegbar; das Repository wurde stattdessen als ZIP-Archiv heruntergeladen.",
        "ja-JP": "git が利用できないため、ZIP アーカイブとしてダウンロードしました。",
        "ko-KR": "git을 사용할 수 없어 ZIP 압축 파일로 다운로드했습니다.",
        "pt-BR": "O git nao esta disponivel; o repositorio foi baixado como arquivo ZIP.",
    },
    "warning_clone_fallback": {
        "zh-CN": "git clone 失败，已改为下载默认分支的 ZIP 压缩包。",
        "en-US": "git clone failed; the default branch was downloaded as a ZIP archive instead.",
        "es-ES": "git clone fallo; se descargo la rama predeterminada como archivo ZIP.",
        "fr-FR": "git clone a echoue ; la branche par defaut a ete telechargee en archive ZIP.",
        "de-DE": "git clone ist fehlgeschlagen; der Standardzweig wurde als ZIP-Archiv heruntergeladen.",
        "ja-JP": "git clone に失敗したため、既定ブランチを ZIP アーカイブでダウンロードしました。",
        "ko-KR": "git clone이 실패하여 기본 브랜치를 ZIP 압축 파일로 다운로드했습니다.",
        "pt-BR": "O git clone falhou; o branch padrao foi baixado como arquivo ZIP.",
    },
}

SUPPORTED_LIBRARY_LANGUAGES = tuple(LIBRARY_COPY["library_root_unavailable"].keys())

DEFAULT_LIBRARY_LANGUAGE = "en-US"


def resolve_library_language(language: str | None) -> str:
    """Map any language tag onto one of the eight supported copy languages."""

    normalized = str(language or "").strip()
    if normalized in LIBRARY_COPY["library_root_unavailable"]:
        return normalized
    prefix = normalized.split("-", 1)[0].lower()
    if prefix:
        for candidate in SUPPORTED_LIBRARY_LANGUAGES:
            if candidate.split("-", 1)[0].lower() == prefix:
                return candidate
    return DEFAULT_LIBRARY_LANGUAGE


def library_message(code: str, language: str | None, **params: object) -> str:
    """Render one user-visible library message in the workspace language.

    Unknown codes fall back to the code itself so a missing translation can
    never crash a request; missing parameters are left visible instead of
    raising, so the message stays diagnosable.
    """

    templates = LIBRARY_COPY.get(code)
    if not templates:
        return code
    template = templates.get(resolve_library_language(language)) or templates[DEFAULT_LIBRARY_LANGUAGE]
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


__all__ = [
    "DEFAULT_LIBRARY_LANGUAGE",
    "LIBRARY_COPY",
    "SUPPORTED_LIBRARY_LANGUAGES",
    "library_message",
    "resolve_library_language",
]
