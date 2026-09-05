# Read the file
with open('shared/src/sidebarCommands.ts', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace all command calls with multi-language versions
replacements = [
    # ('/打开 教练', "/open coach") -> new pattern
]

# Define all translations for each command
commands_translations = {
    "open-coach": {
        "zh-CN": "/打开 教练",
        "en-US": "/open coach",
        "es-ES": "/abrir coach",
        "fr-FR": "/ouvrir coach",
        "de-DE": "/coach oeffnen",
        "ja-JP": "/coachを開く",
        "ko-KR": "/coach 열기",
        "pt-BR": "/abrir coach",
    },
    "open-plan": {
        "zh-CN": "/打开 计划",
        "en-US": "/open plan",
        "es-ES": "/abrir plan",
        "fr-FR": "/ouvrir plan",
        "de-DE": "/plan oeffnen",
        "ja-JP": "/planを開く",
        "ko-KR": "/plan 열기",
        "pt-BR": "/abrir plan",
    },
    "open-settings": {
        "zh-CN": "/打开 设置",
        "en-US": "/open settings",
        "es-ES": "/abrir config",
        "fr-FR": "/ouvrir params",
        "de-DE": "/einstellungen oeffnen",
        "ja-JP": "/設定を開く",
        "ko-KR": "/설정 열기",
        "pt-BR": "/abrir config",
    },
    "lang-zh": {
        "zh-CN": "/语言 中文",
        "en-US": "/lang zh",
        "es-ES": "/idioma zh",
        "fr-FR": "/langue zh",
        "de-DE": "/sprache zh",
        "ja-JP": "/言語 zh",
        "ko-KR": "/언어 zh",
        "pt-BR": "/idioma zh",
    },
    "lang-en": {
        "zh-CN": "/语言 英文",
        "en-US": "/lang en",
        "es-ES": "/idioma en",
        "fr-FR": "/langue en",
        "de-DE": "/sprache en",
        "ja-JP": "/言語 en",
        "ko-KR": "/언어 en",
        "pt-BR": "/idioma en",
    },
    "mode-coach": {
        "zh-CN": "/模式 引导",
        "en-US": "/mode coach",
        "es-ES": "/modo coach",
        "fr-FR": "/mode coach",
        "de-DE": "/modus coach",
        "ja-JP": "/モード coach",
        "ko-KR": "/모드 coach",
        "pt-BR": "/modo coach",
    },
    "mode-balanced": {
        "zh-CN": "/模式 平衡",
        "en-US": "/mode balanced",
        "es-ES": "/modo balance",
        "fr-FR": "/mode balance",
        "de-DE": "/modus balance",
        "ja-JP": "/モード balance",
        "ko-KR": "/모드 balance",
        "pt-BR": "/modo balance",
    },
    "mode-direct": {
        "zh-CN": "/模式 直接",
        "en-US": "/mode direct",
        "es-ES": "/modo directo",
        "fr-FR": "/mode direct",
        "de-DE": "/modus direkt",
        "ja-JP": "/モード 直接",
        "ko-KR": "/모드 직접",
        "pt-BR": "/modo direto",
    },
    "detail-focused": {
        "zh-CN": "/强度 聚焦",
        "en-US": "/detail focused",
        "es-ES": "/detalle focus",
        "fr-FR": "/detail focus",
        "de-DE": "/detail focus",
        "ja-JP": "/詳細 focus",
        "ko-KR": "/디테일 포커스",
        "pt-BR": "/detalhe focus",
    },
    "detail-balanced": {
        "zh-CN": "/强度 标准",
        "en-US": "/detail balanced",
        "es-ES": "/detalle balance",
        "fr-FR": "/detail balance",
        "de-DE": "/detail balance",
        "ja-JP": "/詳細 balance",
        "ko-KR": "/디테일 밸런스",
        "pt-BR": "/detalhe balance",
    },
    "detail-full": {
        "zh-CN": "/强度 完整",
        "en-US": "/detail full",
        "es-ES": "/detalle full",
        "fr-FR": "/detail full",
        "de-DE": "/detail voll",
        "ja-JP": "/詳細 完全",
        "ko-KR": "/디테일 풀",
        "pt-BR": "/detalhe full",
    },
    "attach-all": {
        "zh-CN": "/附带 全部",
        "en-US": "/attach all",
        "es-ES": "/adjuntar todo",
        "fr-FR": "/attacher tout",
        "de-DE": "/anhang alles",
        "ja-JP": "/添付 全部",
        "ko-KR": "/첨부 전부",
        "pt-BR": "/anexar tudo",
    },
    "attach-none": {
        "zh-CN": "/附带 关闭",
        "en-US": "/attach none",
        "es-ES": "/adjuntar ninguno",
        "fr-FR": "/attacher rien",
        "de-DE": "/anhang keine",
        "ja-JP": "/添付 なし",
        "ko-KR": "/첨부 없음",
        "pt-BR": "/anexar nenhum",
    },
    "file-on": {
        "zh-CN": "/文件 开",
        "en-US": "/file on",
        "es-ES": "/archivo on",
        "fr-FR": "/fichier on",
        "de-DE": "/datei an",
        "ja-JP": "/ファイル on",
        "ko-KR": "/파일 on",
        "pt-BR": "/arquivo on",
    },
    "file-off": {
        "zh-CN": "/文件 关",
        "en-US": "/file off",
        "es-ES": "/archivo off",
        "fr-FR": "/fichier off",
        "de-DE": "/datei aus",
        "ja-JP": "/ファイル off",
        "ko-KR": "/파일 off",
        "pt-BR": "/arquivo off",
    },
    "selection-on": {
        "zh-CN": "/选区 开",
        "en-US": "/selection on",
        "es-ES": "/seleccion on",
        "fr-FR": "/selection on",
        "de-DE": "/auswahl an",
        "ja-JP": "/選択 on",
        "ko-KR": "/선택 on",
        "pt-BR": "/selecao on",
    },
    "selection-off": {
        "zh-CN": "/选区 关",
        "en-US": "/selection off",
        "es-ES": "/seleccion off",
        "fr-FR": "/selection off",
        "de-DE": "/auswahl aus",
        "ja-JP": "/選択 off",
        "ko-KR": "/선택 off",
        "pt-BR": "/selecao off",
    },
    "diagnostics-on": {
        "zh-CN": "/诊断 开",
        "en-US": "/diagnostics on",
        "es-ES": "/diagnosticos on",
        "fr-FR": "/diagnostics on",
        "de-DE": "/diagnose an",
        "ja-JP": "/診断 on",
        "ko-KR": "/진단 on",
        "pt-BR": "/diagnosticos on",
    },
    "diagnostics-off": {
        "zh-CN": "/诊断 关",
        "en-US": "/diagnostics off",
        "es-ES": "/diagnosticos off",
        "fr-FR": "/diagnostics off",
        "de-DE": "/diagnose aus",
        "ja-JP": "/診断 off",
        "ko-KR": "/진단 off",
        "pt-BR": "/diagnosticos off",
    },
    "related-on": {
        "zh-CN": "/相关 开",
        "en-US": "/related on",
        "es-ES": "/relacionados on",
        "fr-FR": "/lies on",
        "de-DE": "/verwandte an",
        "ja-JP": "/関連 on",
        "ko-KR": "/관련 on",
        "pt-BR": "/relacionados on",
    },
    "related-off": {
        "zh-CN": "/相关 关",
        "en-US": "/related off",
        "es-ES": "/relacionados off",
        "fr-FR": "/lies off",
        "de-DE": "/verwandte aus",
        "ja-JP": "/関連 off",
        "ko-KR": "/관련 off",
        "pt-BR": "/relacionados off",
    },
    "follow-on": {
        "zh-CN": "/跟随 开",
        "en-US": "/follow on",
        "es-ES": "/seguir on",
        "fr-FR": "/suivre on",
        "de-DE": "/folgen an",
        "ja-JP": "/フォロ on",
        "ko-KR": "/팔로우 on",
        "pt-BR": "/seguir on",
    },
    "follow-off": {
        "zh-CN": "/跟随 关",
        "en-US": "/follow off",
        "es-ES": "/seguir off",
        "fr-FR": "/suivre off",
        "de-DE": "/folgen aus",
        "ja-JP": "/フォロ off",
        "ko-KR": "/팔로우 off",
        "pt-BR": "/seguir off",
    },
}

# Update the command calls
lines = content.split('\n')
new_lines = []
for line in lines:
    # Check if this is a command call
    for cmd_id, translations in commands_translations.items():
        if f'command("{cmd_id}"' in line:
            zh = translations["zh-CN"]
            en = translations["en-US"]
            es = translations["es-ES"]
            fr = translations["fr-FR"]
            de = translations["de-DE"]
            ja = translations["ja-JP"]
            ko = translations["ko-KR"]
            pt = translations["pt-BR"]
            # Build new command call
            new_line = f'  command("{cmd_id}", {line.split(",")[1]},{line.split(",")[2]}, "{en}", "{es}", "{fr}", "{de}", "{ja}", "{ko}", "{pt}"),'
            line = new_line
            break
    new_lines.append(line)

content = '\n'.join(new_lines)

with open('shared/src/sidebarCommands.ts', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated sidebarCommands.ts with all language translations")