import { trainerCommands } from "../../../../shared/src/commands";
import { resolveCopy } from "./i18n/copy";
import type {
  ActiveWorkbenchView,
  BootstrapData,
  ComposerLanguage,
  LearningPlan,
  PlanRuntimeStatus,
  PlanStage,
  ResourceRecord,
  TaskSpec,
  TrainerWorkspaceAdmission,
  WebviewAction,
} from "./types";

export type BrowserPreviewBootstrap = BootstrapData & {
  hasFormalPlan?: boolean;
  activeView?: ActiveWorkbenchView;
};

export type BrowserPreviewPatch = Partial<BootstrapData> & {
  hasFormalPlan?: boolean;
};

export type BrowserPreviewActionResult = {
  patch?: BrowserPreviewPatch;
  tone: "info" | "success" | "error";
  message: string;
};

type PreviewActionCopy = {
  planTitle: (goal: string) => string;
  planSummary: string;
  firstStage: string;
  firstObjective: (goal: string) => string;
  secondStage: string;
  secondObjective: (goal: string) => string;
  thirdStage: string;
  thirdObjective: (goal: string) => string;
  verification: string;
  nextAfterCurrent: string;
  generateSucceeded: string;
  planFrozen: string;
  planResumed: string;
  missingPlan: string;
  taskReady: (stage: string) => string;
  resourceOpened: (title: string) => string;
  resourcesRefreshed: (count: number) => string;
  trainingCardReady: string;
  unsupported: string;
  evaluateCurrentFileMissing: string;
  fallbackGoal: string;
  continueInCoach: string;
  localPreviewTaskConstraint: string;
};

const EN_PREVIEW_ACTION_COPY: PreviewActionCopy = {
  planTitle: (goal) => `Learning path for "${goal}"`,
  planSummary: "Start with one finishable outcome, then practice, verify, and reflect.",
  firstStage: "Define a first-week outcome",
  firstObjective: (goal) => `Write one visible outcome you can finish this week for "${goal}".`,
  secondStage: "Complete one small practice",
  secondObjective: (goal) => `Use a short practice to move "${goal}" into a state you can show.`,
  thirdStage: "Verify and reflect",
  thirdObjective: (goal) => `Verify the result for "${goal}" and record what to adjust next time.`,
  verification: "You can name the first-week outcome, how to verify it, and your available time.",
  nextAfterCurrent: "Return to Coach with the result, then shape the next step.",
  generateSucceeded: "A local preview plan was created from your current goal.",
  planFrozen: "The preview plan is frozen; normal conversation will not rewrite it.",
  planResumed: "The preview plan is editable again.",
  missingPlan: "Create a plan from your goal first.",
  taskReady: (stage) => `The current task is ready: "${stage}".`,
  resourceOpened: (title) => `Located "${title}" in the preview. Use VS Code to open the full resource.`,
  resourcesRefreshed: (count) => `Refreshed local preview status for ${count} resource${count === 1 ? "" : "s"}. Run real file indexing in VS Code.`,
  trainingCardReady: "A local demo training card is ready. It does not change the real workspace.",
  unsupported: "This browser preview action does not change real data. Continue in the VS Code sidebar.",
  evaluateCurrentFileMissing:
    "The browser preview has no current IDE file. Open the file in VS Code, then use Verify current file there.",
  fallbackGoal: "your current learning goal",
  continueInCoach: "Continue in Coach",
  localPreviewTaskConstraint: "This is a local browser-preview task and does not change a real workspace.",
};

const ZH_PREVIEW_ACTION_COPY: PreviewActionCopy = {
  planTitle: (goal) => `\u56f4\u7ed5\u201c${goal}\u201d\u7684\u5b66\u4e60\u8def\u5f84`,
  planSummary: "\u6559\u7ec3\u521a\u521a\u5148\u5b8c\u6210\u4e00\u4e2a\u53ef\u4ea4\u4ed8\u7ed3\u679c\uff0c\u518d\u7ec3\u4e60\u3001\u9a8c\u8bc1\u548c\u590d\u76d8\u3002",
  firstStage: "\u5b9a\u4e49\u7b2c\u4e00\u5468\u7ed3\u679c",
  firstObjective: (goal) => `\u4e3a\u201c${goal}\u201d\u5199\u4e0b\u672c\u5468\u80fd\u5b8c\u6210\u7684\u4e00\u4e2a\u53ef\u89c1\u7ed3\u679c\u3002`,
  secondStage: "\u5b8c\u6210\u4e00\u6b21\u5c0f\u7ec3\u4e60",
  secondObjective: (goal) => `\u7528\u4e00\u6b21\u77ed\u7ec3\u4e60\u628a\u201c${goal}\u201d\u63a8\u8fdb\u5230\u53ef\u5c55\u793a\u72b6\u6001\u3002`,
  thirdStage: "\u9a8c\u8bc1\u5e76\u590d\u76d8",
  thirdObjective: (goal) => `\u9a8c\u8bc1\u201c${goal}\u201d\u7684\u7ed3\u679c\uff0c\u5e76\u8bb0\u5f55\u4e0b\u6b21\u8981\u8c03\u6574\u7684\u5730\u65b9\u3002`,
  verification: "\u4f60\u80fd\u8bf4\u6e05\u7b2c\u4e00\u5468\u7ed3\u679c\u3001\u9a8c\u8bc1\u65b9\u5f0f\u548c\u53ef\u7528\u65f6\u95f4\u3002",
  nextAfterCurrent: "\u5e26\u7740\u7ed3\u679c\u56de\u5230 Coach\uff0c\u518d\u786e\u5b9a\u4e0b\u4e00\u6b65\u3002",
  generateSucceeded: "\u5df2\u6839\u636e\u5f53\u524d\u76ee\u6807\u521b\u5efa\u672c\u5730\u9884\u89c8\u8ba1\u5212\u3002",
  planFrozen: "\u9884\u89c8\u8ba1\u5212\u5df2\u51bb\u7ed3\uff1b\u666e\u901a\u5bf9\u8bdd\u4e0d\u4f1a\u6539\u5199\u5b83\u3002",
  planResumed: "\u9884\u89c8\u8ba1\u5212\u5df2\u6062\u590d\u53ef\u7f16\u8f91\u3002",
  missingPlan: "\u8bf7\u5148\u6839\u636e\u76ee\u6807\u521b\u5efa\u8ba1\u5212\u3002",
  taskReady: (stage) => `\u5f53\u524d\u4efb\u52a1\u5df2\u51c6\u5907\u597d\uff1a\u201c${stage}\u201d\u3002`,
  resourceOpened: (title) => `\u5df2\u5728\u9884\u89c8\u4e2d\u5b9a\u4f4d\u201c${title}\u201d\u3002\u5b8c\u6574\u8d44\u6e90\u8bf7\u5728 VS Code \u4e2d\u6253\u5f00\u3002`,
  resourcesRefreshed: (count) => `\u5df2\u5237\u65b0 ${count} \u4e2a\u8d44\u6599\u7684\u672c\u5730\u9884\u89c8\u72b6\u6001\u3002\u771f\u5b9e\u6587\u4ef6\u7d22\u5f15\u8bf7\u5728 VS Code \u4e2d\u6267\u884c\u3002`,
  trainingCardReady: "\u672c\u5730\u9884\u89c8\u8bad\u7ec3\u5361\u5df2\u51c6\u5907\u597d\uff0c\u4e0d\u4f1a\u4fee\u6539\u771f\u5b9e\u5de5\u4f5c\u533a\u3002",
  unsupported: "\u6b64\u6d4f\u89c8\u5668\u9884\u89c8\u64cd\u4f5c\u4e0d\u4f1a\u4fee\u6539\u771f\u5b9e\u6570\u636e\u3002\u8bf7\u56de\u5230 VS Code \u4fa7\u680f\u7ee7\u7eed\u3002",
  evaluateCurrentFileMissing:
    "\u6d4f\u89c8\u5668\u9884\u89c8\u4e2d\u6ca1\u6709\u5f53\u524d IDE \u6587\u4ef6\u3002\u8bf7\u5148\u5728 VS Code \u4e2d\u6253\u5f00\u8be5\u6587\u4ef6\uff0c\u518d\u5728\u90a3\u91cc\u4f7f\u7528\u201c\u9a8c\u8bc1\u5f53\u524d\u6587\u4ef6\u201d\u3002",
  fallbackGoal: "\u5f53\u524d\u5b66\u4e60\u76ee\u6807",
  continueInCoach: "\u56de\u5230 Coach",
  localPreviewTaskConstraint: "\u6d4f\u89c8\u5668\u9884\u89c8\u53ea\u66f4\u65b0\u6f14\u793a\u72b6\u6001\uff1b\u771f\u5b9e\u6587\u4ef6\u548c\u5de5\u4f5c\u533a\u64cd\u4f5c\u8bf7\u5728 VS Code \u4e2d\u5b8c\u6210\u3002",
};

const PREVIEW_ACTION_COPY: Record<ComposerLanguage, PreviewActionCopy> = {
  "zh-CN": ZH_PREVIEW_ACTION_COPY,
  "en-US": EN_PREVIEW_ACTION_COPY,
  "es-ES": EN_PREVIEW_ACTION_COPY,
  "fr-FR": EN_PREVIEW_ACTION_COPY,
  "de-DE": EN_PREVIEW_ACTION_COPY,
  "ja-JP": EN_PREVIEW_ACTION_COPY,
  "ko-KR": EN_PREVIEW_ACTION_COPY,
  "pt-BR": EN_PREVIEW_ACTION_COPY,
};

/*
const LEGACY_PREVIEW_ACTION_COPY: Record<ComposerLanguage, PreviewActionCopy> = {
"zh-CN":{planTitle:t=>`鈥?{t}鈥?鐨勫涔犺矾寰刞,planSummary:"鍏堝畬鎴愪竴涓皬鎴愭灉锛屽啀缁冧範銆侀獙璇佸苟澶嶇洏銆?,firstStage:"纭畾绗竴鍛ㄧ殑璧锋鎴愭灉",firstObjective:t=>`鍥寸粫鈥?{t}鈥濆啓涓嬩竴涓繖鍛ㄨ兘瀹屾垚鐨勫彲瑙佹垚鏋溿€俙,secondStage:"瀹屾垚涓€娆℃渶灏忕粌涔?,secondObjective:t=>`鐢ㄤ竴涓煭缁冧範鎶娾€?{t}鈥濇帹杩涘埌鍙睍绀虹殑鐘舵€併€俙,thirdStage:"楠岃瘉骞跺鐩?,thirdObjective:t=>`楠岃瘉鈥?{t}鈥濈殑鎴愭灉锛屽苟璁板綍涓嬩竴娆＄粌涔犺璋冩暣浠€涔堛€俙,verification:"鑳借娓呯涓€鍛ㄦ垚鏋溿€侀獙璇佹柟寮忓拰鍙姇鍏ユ椂闂淬€?,nextAfterCurrent:"甯︾潃缁撴灉鍥炲埌 Coach锛屽啀瀹夋帓涓嬩竴姝ャ€?,generateSucceeded:"宸叉寜褰撳墠鐩爣鐢熸垚鏈湴棰勮璁″垝銆?,planFrozen:"棰勮璁″垝宸查攣瀹氾紱鏅€氬璇濅笉浼氭敼鍐欏畠銆?,planResumed:"棰勮璁″垝宸叉仮澶嶇紪杈戙€?,missingPlan:"璇峰厛鏍规嵁鐩爣鐢熸垚璁″垝銆?,taskReady:t=>`宸插噯澶囧綋鍓嶄换鍔★細鈥?{t}鈥濄€俙,resourceOpened:t=>`宸插湪棰勮涓畾浣嶁€?{t}鈥濄€傚畬鏁存墦寮€璇蜂娇鐢?VS Code銆俙,resourcesRefreshed:t=>`宸插埛鏂?${t} 椤硅祫鏂欑殑鏈湴棰勮鐘舵€併€傜湡瀹炴枃浠剁储寮曡鍦?VS Code 涓繍琛屻€俙,trainingCardReady:"宸茬敓鎴愪竴寮犳湰鍦版紨绀鸿缁冨崱锛屼笉浼氫慨鏀圭湡瀹炲伐浣滃尯銆?,unsupported:"杩欎釜鍔ㄤ綔鍦ㄦ祻瑙堝櫒棰勮涓笉浼氫慨鏀圭湡瀹炴暟鎹€傝鍦?VS Code 渚ф爮涓户缁€?,fallbackGoal:"褰撳墠瀛︿範鐩爣",continueInCoach:"鍥炲埌 Coach 缁х画",localPreviewTaskConstraint:"杩欐槸娴忚鍣ㄩ瑙堜腑鐨勬湰鍦颁换鍔★紝涓嶄細淇敼鐪熷疄宸ヤ綔鍖恒€?},"en-US":{planTitle:t=>`Learning path for "${t}"`,planSummary:"Start with one finishable outcome, then practice, verify, and reflect.",firstStage:"Define a first-week outcome",firstObjective:t=>`Write one visible outcome you can finish this week for "${t}".`,secondStage:"Complete one small practice",secondObjective:t=>`Use a short practice to move "${t}" into a state you can show.`,thirdStage:"Verify and reflect",thirdObjective:t=>`Verify the result for "${t}" and record what to adjust next time.`,verification:"You can name the first-week outcome, how to verify it, and your available time.",nextAfterCurrent:"Return to Coach with the result, then shape the next step.",generateSucceeded:"A local preview plan was created from your current goal.",planFrozen:"The preview plan is frozen; normal conversation will not rewrite it.",planResumed:"The preview plan is editable again.",missingPlan:"Create a plan from your goal first.",taskReady:t=>`The current task is ready: "${t}".`,resourceOpened:t=>`Located "${t}" in the preview. Use VS Code to open the full resource.`,resourcesRefreshed:t=>`Refreshed local preview status for ${t} resource${t===1?"":"s"}. Run real file indexing in VS Code.`,trainingCardReady:"A local demo training card is ready. It does not change the real workspace.",unsupported:"This browser preview action does not change real data. Continue in the VS Code sidebar.",fallbackGoal:"your current learning goal",continueInCoach:"Continue in Coach",localPreviewTaskConstraint:"This is a local browser-preview task and does not change a real workspace."},"es-ES":{planTitle:t=>`Ruta de aprendizaje para "${t}"`,planSummary:"Empieza con un resultado alcanzable, luego practica, verifica y reflexiona.",firstStage:"Definir un resultado para la primera semana",firstObjective:t=>`Escribe un resultado visible que puedas terminar esta semana para "${t}".`,secondStage:"Completar una practica pequena",secondObjective:t=>`Usa una practica breve para llevar "${t}" a un estado que puedas mostrar.`,thirdStage:"Verificar y reflexionar",thirdObjective:t=>`Verifica el resultado de "${t}" y anota que ajustar la proxima vez.`,verification:"Puedes nombrar el resultado de la primera semana, como verificarlo y tu tiempo disponible.",nextAfterCurrent:"Vuelve al Coach con el resultado y prepara el siguiente paso.",generateSucceeded:"Se creo un plan de vista previa local desde tu objetivo actual.",planFrozen:"El plan de vista previa esta bloqueado; la conversacion normal no lo reescribira.",planResumed:"El plan de vista previa se puede editar de nuevo.",missingPlan:"Primero crea un plan desde tu objetivo.",taskReady:t=>`La tarea actual esta lista: "${t}".`,resourceOpened:t=>`Se localizo "${t}" en la vista previa. Usa VS Code para abrir el recurso completo.`,resourcesRefreshed:t=>`Se actualizo el estado local de vista previa para ${t} recurso${t===1?"":"s"}. Ejecuta la indexacion real en VS Code.`,trainingCardReady:"Se preparo una tarjeta de entrenamiento local. No cambia el espacio de trabajo real.",unsupported:"Esta accion de vista previa no cambia datos reales. Continua en la barra lateral de VS Code.",fallbackGoal:"tu objetivo de aprendizaje actual",continueInCoach:"Continuar en Coach",localPreviewTaskConstraint:"Esta es una tarea local de vista previa en el navegador y no modifica un espacio de trabajo real."},"fr-FR":{planTitle:t=>`Parcours d'apprentissage pour 芦 ${t} 禄`,planSummary:"Commencez par un resultat atteignable, puis pratiquez, verifiez et prenez du recul.",firstStage:"Definir un resultat pour la premiere semaine",firstObjective:t=>`Definissez un resultat visible a terminer cette semaine pour 芦 ${t} 禄.`,secondStage:"Faire une petite pratique",secondObjective:t=>`Faites une pratique courte pour rendre 芦 ${t} 禄 montrable.`,thirdStage:"Verifier et reflechir",thirdObjective:t=>`Verifiez le resultat pour 芦 ${t} 禄 et notez quoi ajuster ensuite.`,verification:"Vous pouvez nommer le resultat de la premiere semaine, sa verification et votre temps disponible.",nextAfterCurrent:"Revenez au Coach avec le resultat, puis preparez la suite.",generateSucceeded:"Un plan de previsualisation local a ete cree depuis votre objectif actuel.",planFrozen:"Le plan de previsualisation est fige ; la conversation normale ne le reecrira pas.",planResumed:"Le plan de previsualisation est a nouveau modifiable.",missingPlan:"Creez d'abord un plan depuis votre objectif.",taskReady:t=>`La tache actuelle est prete : 芦 ${t} 禄.`,resourceOpened:t=>`芦 ${t} 禄 est localise dans la previsualisation. Utilisez VS Code pour ouvrir la ressource complete.`,resourcesRefreshed:t=>`Etat local de previsualisation actualise pour ${t} ressource${t===1?"":"s"}. Lancez l'indexation reelle dans VS Code.`,trainingCardReady:"Une carte d'entrainement locale est prete. Elle ne modifie pas l'espace de travail reel.",unsupported:"Cette action de previsualisation ne modifie aucune donnee reelle. Continuez dans la barre laterale VS Code.",fallbackGoal:"votre objectif d'apprentissage actuel",continueInCoach:"Continuer dans Coach",localPreviewTaskConstraint:"Cette tache locale de previsualisation dans le navigateur ne modifie pas l'espace de travail reel."},"de-DE":{planTitle:t=>`Lernpfad fur 鈥?{t}鈥渀,planSummary:"Beginne mit einem erreichbaren Ergebnis, dann ube, prufe und reflektiere.",firstStage:"Ergebnis fur die erste Woche festlegen",firstObjective:t=>`Lege ein sichtbares Ergebnis fest, das du diese Woche fur 鈥?{t}鈥?schaffen kannst.`,secondStage:"Eine kleine Ubung abschliessen",secondObjective:t=>`Nutze eine kurze Ubung, um 鈥?{t}鈥?in einen zeigbaren Stand zu bringen.`,thirdStage:"Prufen und reflektieren",thirdObjective:t=>`Prufe das Ergebnis fur 鈥?{t}鈥?und notiere, was du nachstes Mal anpasst.`,verification:"Du kannst das Wochenziel, die Prufung und deine verfugbare Zeit benennen.",nextAfterCurrent:"Kehre mit dem Ergebnis zum Coach zuruck und plane dann den nachsten Schritt.",generateSucceeded:"Ein lokaler Vorschaueplan wurde aus deinem aktuellen Ziel erstellt.",planFrozen:"Der Vorschaueplan ist gesperrt; normale Gesprache schreiben ihn nicht um.",planResumed:"Der Vorschaueplan kann wieder bearbeitet werden.",missingPlan:"Erstelle zuerst einen Plan aus deinem Ziel.",taskReady:t=>`Die aktuelle Aufgabe ist bereit: 鈥?{t}鈥?`,resourceOpened:t=>`鈥?{t}鈥?wurde in der Vorschau gefunden. Offne die vollstandige Ressource in VS Code.`,resourcesRefreshed:t=>`Lokaler Vorschauzustand fur ${t} Ressource${t===1?"":"n"} aktualisiert. Fuhre die echte Indexierung in VS Code aus.`,trainingCardReady:"Eine lokale Trainingskarte ist bereit. Der echte Arbeitsbereich bleibt unverandert.",unsupported:"Diese Vorschauaktion andert keine echten Daten. Fahre in der VS Code-Seitenleiste fort.",fallbackGoal:"dein aktuelles Lernziel",continueInCoach:"Im Coach fortfahren",localPreviewTaskConstraint:"Dies ist eine lokale Browser-Vorschauaufgabe und andert keinen echten Arbeitsbereich."},"ja-JP":{planTitle:t=>`銆?{t}銆嶃伄瀛︾繏銉椼儵銉砢,planSummary:"銇俱仛閬旀垚銇с亶銈嬫垚鏋溿倰涓€銇ゆ焙銈併仸銇嬨倝銆佺反缈掋€佹瑷笺€佹尟銈婅繑銈娿倰閫层倎銇俱仚銆?,firstStage:"1閫辩洰銇垚鏋溿倰姹恒倎銈?,firstObjective:t=>`銆?{t}銆嶃伀銇ゃ亜銇︺€佷粖閫变腑銇祩銇堛倝銈屻倠瑕嬨亪銈嬫垚鏋溿倰涓€銇ゆ浉銇嶅嚭銇椼伨銇欍€俙,secondStage:"灏忋仌銇反缈掋倰涓€銇ょ祩銇堛倠",secondObjective:t=>`鐭亜绶寸繏銇с€?{t}銆嶃倰瑕嬨仜銈夈倢銈嬬姸鎱嬨伨銇ч€层倎銇俱仚銆俙,thirdStage:"妞滆銇椼仸鎸倞杩斻倠",thirdObjective:t=>`銆?{t}銆嶃伄绲愭灉銈掓瑷笺仐銆佹銇鏁淬仚銈嬬偣銈掕閷层仐銇俱仚銆俙,verification:"1閫辩洰銇垚鏋溿€佹瑷兼柟娉曘€佷娇銇堛倠鏅傞枔銈掕█钁夈伀銇с亶銇俱仚銆?,nextAfterCurrent:"绲愭灉銈掓寔銇ｃ仸 Coach 銇埢銈娿€佹銇竴姝┿倰绲勩伩绔嬨仸銇俱仚銆?,generateSucceeded:"鐝惧湪銇洰妯欍亱銈夈儹銉笺偒銉伄銉椼儸銉撱儱銉笺儣銉┿兂銈掍綔鎴愩仐銇俱仐銇熴€?,planFrozen:"銉椼儸銉撱儱銉笺儣銉┿兂銈掑浐瀹氥仐銇俱仐銇熴€傞€氬父銇細瑭便仹銇浉銇嶆彌銇堛伨銇涖倱銆?,planResumed:"銉椼儸銉撱儱銉笺儣銉┿兂銈掑啀銇崇法闆嗐仹銇嶃倠銈堛亞銇仐銇俱仐銇熴€?,missingPlan:"鍏堛伀鐩銇嬨倝銉椼儵銉炽倰浣滄垚銇椼仸銇忋仩銇曘亜銆?,taskReady:t=>`鐝惧湪銇偪銈广偗銈掔敤鎰忋仐銇俱仐銇? 銆?{t}銆嶃€俙,resourceOpened:t=>`銉椼儸銉撱儱銉煎唴銇с€?{t}銆嶃倰纰鸿獚銇椼伨銇椼仧銆傚畬鍏ㄣ伀闁嬨亸銇伅 VS Code 銈掍娇鐢ㄣ仐銇︺亸銇犮仌銇勩€俙,resourcesRefreshed:t=>`${t} 浠躲伄璩囨枡銇儹銉笺偒銉儣銉儞銉ャ兗鐘舵厠銈掓洿鏂般仐銇俱仐銇熴€傚疅闅涖伄绱㈠紩銇?VS Code 銇у疅琛屻仐銇︺亸銇犮仌銇勩€俙,trainingCardReady:"銉兗銈儷銇儑銉㈠缈掋偒銉笺儔銈掔敤鎰忋仐銇俱仐銇熴€傚疅闅涖伄銉兗銈偣銉氥兗銈广伅澶夋洿銇椼伨銇涖倱銆?,unsupported:"銇撱伄銉栥儵銈︺偠銉笺儣銉儞銉ャ兗鎿嶄綔銇с伅瀹熼殯銇儑銉笺偪銇鏇淬仌銈屻伨銇涖倱銆俈S Code 銇偟銈ゃ儔銉愩兗銇х稓銇戙仸銇忋仩銇曘亜銆?,fallbackGoal:"鐝惧湪銇缈掔洰妯?,continueInCoach:"Coach 銇х稓銇戙倠",localPreviewTaskConstraint:"銇撱倢銇儢銉┿偊銈躲兗銉椼儸銉撱儱銉煎唴銇儹銉笺偒銉偪銈广偗銇с亗銈娿€佸疅闅涖伄銉兗銈偣銉氥兗銈广伅澶夋洿銇椼伨銇涖倱銆?},"ko-KR":{planTitle:t=>`鈥?{t}鈥?頃欖姷 瓴诫`,planSummary:"毹检爛 雭濍偧 靾?鞛堧姅 瓴瓣臣 頃橂倶毳?鞝曧暅 霋?鞐办姷, 瓴€歃? 須岅碃毳?歆勴枆頃╇媹雼?",firstStage:"觳?欤?瓴瓣臣 鞝曧晿旮?,firstObjective:t=>`鈥?{t}鈥濎潉 鞙勴暣 鞚措矆 欤检棎 雭濍偧 靾?鞛堧姅 雸堨棎 氤挫澊電?瓴瓣臣毳?鞝侅姷雼堧嫟.`,secondStage:"鞛戩潃 鞐办姷 頃橂倶 雭濍偞旮?,secondObjective:t=>`歆ъ潃 鞐办姷鞙茧 鈥?{t}鈥濎潉 氤挫棳 欷?靾?鞛堧姅 靸來儨旯岇 歆勴枆頃╇媹雼?`,thirdStage:"瓴€歃濏晿瓿?須岅碃頃橁赴",thirdObjective:t=>`鈥?{t}鈥濎潣 瓴瓣臣毳?瓴€歃濏晿瓿?雼れ潓鞐?臁办爼頃?鞝愳潉 旮半頃╇媹雼?`,verification:"觳?欤?瓴瓣臣, 瓴€歃?氚╇矔, 靷毄頃?靾?鞛堧姅 鞁滉皠鞚?毵愴暊 靾?鞛堨姷雼堧嫟.",nextAfterCurrent:"瓴瓣臣毳?臧€歆€瓿?Coach搿?霃岇晞臧€ 雼れ潓 雼硠毳?毵岆摥雼堧嫟.",generateSucceeded:"順勳灛 氇╉憸搿?搿滌滑 氙鸽Μ氤搓赴 瓿勴殟鞚?毵岆摛鞐堨姷雼堧嫟.",planFrozen:"氙鸽Μ氤搓赴 瓿勴殟鞚?瓿犾爼頄堨姷雼堧嫟. 鞚茧皹 雽€頇旊姅 鞚措ゼ 氚旉靖歆€ 鞎婌姷雼堧嫟.",planResumed:"氙鸽Μ氤搓赴 瓿勴殟鞚?雼れ嫓 韼胳頃?靾?鞛堨姷雼堧嫟.",missingPlan:"毹检爛 氇╉憸鞐愳劀 瓿勴殟鞚?毵岆摐靹胳殧.",taskReady:t=>`順勳灛 鞛戩梾鞚?欷€牍勴枅鞀惦媹雼? 鈥?{t}鈥?`,resourceOpened:t=>`氙鸽Μ氤搓赴鞐愳劀 鈥?{t}鈥濎潉 頇曥澑頄堨姷雼堧嫟. 鞝勳泊 鞛愲電?VS Code鞐愳劀 鞐劯鞖?`,resourcesRefreshed:t=>`${t}臧?鞛愲鞚?搿滌滑 氙鸽Μ氤搓赴 靸來儨毳?靸堧 瓿犾长鞀惦媹雼? 鞁れ牅 靸夓澑鞚€ VS Code鞐愳劀 鞁ろ枆頃橃劯鞖?`,trainingCardReady:"搿滌滑 雿半 頃欖姷 旃措摐毳?欷€牍勴枅鞀惦媹雼? 鞁れ牅 鞛戩梾 瓿店皠鞚€ 氤€瓴巾晿歆€ 鞎婌姷雼堧嫟.",unsupported:"鞚?敫岆澕鞖办爛 氙鸽Μ氤搓赴 霃欖瀾鞚€ 鞁れ牅 雿办澊韯半ゼ 氚旉靖歆€ 鞎婌姷雼堧嫟. VS Code 靷澊霌滊皵鞐愳劀 瓿勳啀頃橃劯鞖?",fallbackGoal:"順勳灛 頃欖姷 氇╉憸",continueInCoach:"Coach鞐愳劀 瓿勳啀",localPreviewTaskConstraint:"鞚?鞛戩梾鞚€ 敫岆澕鞖办爛 氙鸽Μ氤搓赴鞚?搿滌滑 鞛戩梾鞚措┌ 鞁れ牅 鞛戩梾 瓿店皠鞚?氤€瓴巾晿歆€ 鞎婌姷雼堧嫟."},"pt-BR":{planTitle:t=>`Trilha de aprendizado para "${t}"`,planSummary:"Comece com um resultado alcancavel, depois pratique, verifique e reflita.",firstStage:"Definir um resultado para a primeira semana",firstObjective:t=>`Defina um resultado visivel que voce possa concluir esta semana para "${t}".`,secondStage:"Concluir uma pratica pequena",secondObjective:t=>`Use uma pratica curta para levar "${t}" a um estado que voce possa mostrar.`,thirdStage:"Verificar e refletir",thirdObjective:t=>`Verifique o resultado de "${t}" e registre o que ajustar na proxima vez.`,verification:"Voce consegue nomear o resultado da primeira semana, como verifica-lo e seu tempo disponivel.",nextAfterCurrent:"Volte ao Coach com o resultado e prepare o proximo passo.",generateSucceeded:"Um plano local de visualizacao foi criado a partir do seu objetivo atual.",planFrozen:"O plano de visualizacao esta bloqueado; a conversa normal nao o reescrevera.",planResumed:"O plano de visualizacao pode ser editado novamente.",missingPlan:"Primeiro crie um plano a partir do seu objetivo.",taskReady:t=>`A tarefa atual esta pronta: "${t}".`,resourceOpened:t=>`"${t}" foi localizado na visualizacao. Use o VS Code para abrir o recurso completo.`,resourcesRefreshed:t=>`O estado local de visualizacao de ${t} recurso${t===1?"":"s"} foi atualizado. Execute a indexacao real no VS Code.`,trainingCardReady:"Uma ficha de treino local esta pronta. Ela nao altera o espaco de trabalho real.",unsupported:"Esta acao de visualizacao no navegador nao altera dados reais. Continue na barra lateral do VS Code.",fallbackGoal:"seu objetivo de aprendizado atual",continueInCoach:"Continuar no Coach",localPreviewTaskConstraint:"Esta e uma tarefa local da visualizacao no navegador e nao altera um espaco de trabalho real."}};
};

function copyFor(language: ComposerLanguage): PreviewActionCopy {
  return PREVIEW_ACTION_COPY[language] ?? PREVIEW_ACTION_COPY["en-US"];
}
*/
function copyFor(language: ComposerLanguage): PreviewActionCopy {
  return PREVIEW_ACTION_COPY[language] ?? PREVIEW_ACTION_COPY["en-US"];
}

export type BrowserPreviewCoachCopy = Pick<
  PreviewActionCopy,
  | "planSummary"
  | "generateSucceeded"
  | "missingPlan"
  | "taskReady"
  | "verification"
  | "nextAfterCurrent"
  | "continueInCoach"
  | "fallbackGoal"
>;

export function browserPreviewCoachCopy(language: ComposerLanguage): BrowserPreviewCoachCopy {
  return copyFor(language);
}

function cleanText(value: string | undefined): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized || undefined;
}

export function resolveBrowserPreviewGoal(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
): string {
  const profileGoals = Array.isArray(bootstrap.profile?.goals) ? bootstrap.profile.goals : [];
  const candidates = [
    bootstrap.coachFocus?.currentFocus,
    bootstrap.memory?.activeThread?.focusArea,
    profileGoals.find((goal) => cleanText(goal)),
  ];
  for (const candidate of candidates) {
    const goal = cleanText(candidate);
    if (goal) {
      return goal;
    }
  }
  return copyFor(language).fallbackGoal;
}

export function buildGoalAwarePreviewPlan(
  goal: string,
  language: ComposerLanguage,
): LearningPlan {
  const copy = copyFor(language);
  const stages: PlanStage[] = [
    {
      id: "browser-preview-plan-first-outcome",
      title: copy.firstStage,
      objective: copy.firstObjective(goal),
      status: "active",
    },
    {
      id: "browser-preview-plan-small-practice",
      title: copy.secondStage,
      objective: copy.secondObjective(goal),
      status: "queued",
    },
    {
      id: "browser-preview-plan-verify-reflect",
      title: copy.thirdStage,
      objective: copy.thirdObjective(goal),
      status: "queued",
    },
  ];
  return {
    id: "browser-preview-goal-plan",
    title: copy.planTitle(goal),
    frozen: false,
    /*
    cadence: language === "zh-CN" ? "婵絽绻愰幊?3 婵? : "3 times per week",
    */
    cadence: language === "zh-CN" ? "\u6bcf\u5468\u7ec3\u4e60 3 \u6b21" : "3 times per week",
    summary: copy.planSummary,
    stages,
    currentStageId: stages[0].id,
    currentStep: stages[0].objective,
    whyNow: copy.planSummary,
    verifyMethod: [copy.verification],
    nextAfterCurrent: copy.nextAfterCurrent,
  };
}

function buildPreviewPlanRuntime(
  goal: string,
  plan: LearningPlan,
): PlanRuntimeStatus {
  const currentStage = plan.stages.find((stage) => stage.id === plan.currentStageId) ?? plan.stages[0];
  return {
    currentStage: currentStage
      ? {
          id: currentStage.id,
          title: currentStage.title,
          goal: currentStage.objective,
          status: currentStage.status,
        }
      : undefined,
    currentMainThread: {
      scenario: "onboarding",
      focusArea: goal,
      summary: plan.summary,
      nextStep: currentStage?.objective,
      currentStep: plan.currentStep,
      whyNow: plan.whyNow,
      verifyMethod: plan.verifyMethod,
      nextAfterCurrent: plan.nextAfterCurrent,
    },
    reviewPoints: [],
    currentStep: plan.currentStep,
    whyNow: plan.whyNow,
    verifyMethod: plan.verifyMethod,
    nextAfterCurrent: plan.nextAfterCurrent,
    nextTrainingAction: currentStage?.objective,
  };
}

function buildPreviewTask(plan: LearningPlan, language: ComposerLanguage): TaskSpec {
  const currentStage =
    plan.stages.find((stage) => stage.id === plan.currentStageId) ??
    plan.stages.find((stage) => stage.status === "active") ??
    plan.stages[0];
  const copy = copyFor(language);
  return {
    id: `browser-preview-task-${currentStage?.id ?? "current"}`,
    title: currentStage?.title ?? copy.firstStage,
    description: currentStage?.objective ?? plan.currentStep ?? copy.planSummary,
    constraints: [copy.localPreviewTaskConstraint],
    acceptanceCriteria: plan.verifyMethod?.length ? [...plan.verifyMethod] : [copy.verification],
    nextActionLabel: copy.continueInCoach,
  };
}

function commandIdForAction(action: WebviewAction): string | undefined {
  if (action.type === "command/execute") {
    return action.payload.commandId;
  }
  if (action.type === "plan/generate") {
    return trainerCommands.generatePlan;
  }
  if (action.type === "plan/freeze") {
    return trainerCommands.updatePlan;
  }
  if (action.type === "task/next") {
    return trainerCommands.nextTask;
  }
  if (action.type === "resource/open") {
    return trainerCommands.openResource;
  }
  return undefined;
}

function hasFormalPreviewPlan(bootstrap: BrowserPreviewBootstrap): boolean {
  if (typeof bootstrap.hasFormalPlan === "boolean") {
    return bootstrap.hasFormalPlan;
  }
  return Boolean(
    cleanText(bootstrap.plan?.id) &&
      Array.isArray(bootstrap.plan?.stages) &&
      bootstrap.plan.stages.length > 0,
  );
}

export function buildGoalAwarePreviewPlanPatch(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
  explicitGoal?: string,
): BrowserPreviewPatch {
  const goal = cleanText(explicitGoal) ?? resolveBrowserPreviewGoal(bootstrap, language);
  const plan = buildGoalAwarePreviewPlan(goal, language);
  const profile = bootstrap.profile;
  const existingGoals = Array.isArray(profile?.goals) ? profile.goals : [];
  return {
    plan,
    hasFormalPlan: true,
    profile: {
      learnerName: profile?.learnerName ?? "",
      goals: [goal, ...existingGoals.filter((item) => cleanText(item) && item !== goal)],
      weeklyHours: profile?.weeklyHours ?? 3,
      preferredStyle: profile?.preferredStyle ?? "guided",
      answerPolicy: profile?.answerPolicy ?? "auto",
      focusAreas: profile?.focusAreas ?? [],
      targetProject: profile?.targetProject,
      preferredRhythm: profile?.preferredRhythm,
      preferredLearningMode: profile?.preferredLearningMode,
      onboardingRequest: profile?.onboardingRequest,
      projectContext: profile?.projectContext,
    },
    task: buildPreviewTask(plan, language),
    planRuntimeStatus: buildPreviewPlanRuntime(goal, plan),
  };
}

function updatePlanFreezePatch(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
  frozen: boolean,
): BrowserPreviewPatch | undefined {
  if (!hasFormalPreviewPlan(bootstrap)) {
    return undefined;
  }
  const goal = resolveBrowserPreviewGoal(bootstrap, language);
  const plan = { ...bootstrap.plan, frozen };
  return {
    plan,
    hasFormalPlan: true,
    planRuntimeStatus: buildPreviewPlanRuntime(goal, plan),
  };
}

function refreshResourcesPatch(bootstrap: BrowserPreviewBootstrap): BrowserPreviewPatch {
  const now = new Date().toISOString();
  const resources = (bootstrap.resources ?? []).map((resource) => ({
    ...resource,
    status: "ready" as const,
    indexState: "indexed",
    freshness: "fresh" as const,
    updatedAt: now,
  }));
  return {
    resources,
    memory: {
      ...bootstrap.memory,
      sandboxState: bootstrap.memory?.sandboxState
        ? {
            ...bootstrap.memory.sandboxState,
            lastUpdatedAt: now,
          }
        : bootstrap.memory?.sandboxState,
    },
  };
}

function requestedPreviewTrainingCardType(action: WebviewAction): "practice" | "flash" {
  if (action.type !== "command/execute" || !action.payload.payload || typeof action.payload.payload !== "object") {
    return "practice";
  }
  const payload = action.payload.payload;
  const requestedCardType = "cardType" in payload ? payload.cardType : undefined;
  const requestedSubmode = "submode" in payload ? payload.submode : undefined;
  return requestedCardType === "flash" || requestedSubmode === "flash" ? "flash" : "practice";
}

function buildPreviewTrainingCardPatch(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
  cardType: "practice" | "flash",
): BrowserPreviewPatch | undefined {
  const copy = copyFor(language);
  const goal = resolveBrowserPreviewGoal(bootstrap, language);
  const isFlash = cardType === "flash";
  /*
  const title = isFlash
    ? language === "zh-CN"
      ? "闁搞儳鍋涚换鍌濄亹閹惧啿顤呴悗娑崇細缁″嫰鎯勯鐣屽灱闁汇劌瀚崣褔鏌ㄩ娆炬綈闁?
      : "Recall one key rule for the current learning goal"
    : copy.secondStage;
  */
  const title = isFlash
    ? language === "zh-CN"
      ? "\u56de\u987e\u5f53\u524d\u5b66\u4e60\u76ee\u6807\u7684\u4e00\u6761\u5173\u952e\u89c4\u5219"
      : "Recall one key rule for the current learning goal"
    : copy.secondStage;
  /*
  const taskDescription = isFlash
    ? language === "zh-CN"
      ? `闁活潿鍔忛崵婊冾啅鏉堚晜鐣遍悹鍥ㄧ箚椤曗晠寮版惔娑掑亾?{goal}闁靛棗绉跺▓鎴炵▔閳ь剟寮堕垾鍐插綘闂佹鍠涢～澶愬礆濞嗘瑧绀夋鐐存构婵″洦绋夐埀顒佺▔椤忓嫮姣堝〒姘儏閻℃瑩濡存穱?
      : `Explain one key rule for "${goal}" in your own words and give one small example.`
    : copy.secondObjective(goal);
    : copy.secondObjective(goal);
  */
  const taskDescription = isFlash
    ? language === "zh-CN"
      ? `\u7528\u81ea\u5df1\u7684\u8bdd\u89e3\u91ca\u201c${goal}\u201d\u4e2d\u7684\u4e00\u6761\u5173\u952e\u89c4\u5219\uff0c\u5e76\u7ed9\u51fa\u4e00\u4e2a\u5c0f\u4f8b\u5b50\u3002`
      : `Explain one key rule for "${goal}" in your own words and give one small example.`
    : copy.secondObjective(goal);
  const cardId = `browser-preview-${isFlash ? "flash" : "practice"}-card`;
  const card = {
    cardId,
    type: cardType,
    title,
    whyNow: copy.planSummary,
    learningFamily: isFlash ? "theory" as const : "code" as const,
    focusArea: goal,
    targetSkill: goal,
    scenario: taskDescription,
    problemStatement: taskDescription,
    suggestedWorkspaceAction: taskDescription,
    constraints: [
      /*
      language === "zh-CN"
        ? "閺夆晜鐟﹀Σ绋棵硅箛姘兼綌闁革絻鍔戦。鈺冩喆閸儱娅￠柣銊ュ濠€浼村捶閹峰矈鍞茬紓浣稿暙瀹曢亶鏁嶇仦鑲╃憹濞村吋鐭幈銊╁绩閸︻厽鍩傞悗鍦仜娴兼劖鎷呭鍐ㄩ殬闁?
        : "This is a local browser-preview training card and does not change a real workspace.",
      */
      language === "zh-CN"
        ? "\u8fd9\u662f\u672c\u5730\u6d4f\u89c8\u5668\u9884\u89c8\u8bad\u7ec3\u5361\uff0c\u4e0d\u4f1a\u4fee\u6539\u771f\u5b9e\u5de5\u4f5c\u533a\u3002"
        : "This is a local browser-preview training card and does not change a real workspace.",
    ],
    deliverable: taskDescription,
    selfCheck: [copy.verification],
    validationMethod: copy.verification,
    learnerDeliverables: [taskDescription],
    verificationSteps: [copy.verification],
    successSignal: copy.taskReady(title),
    expectedSymbols: [],
    filesToTouch: [],
    hintLadder: [copy.firstObjective(goal), taskDescription],
    commonMistakes: [copy.planSummary],
    stuckRecovery: copy.firstObjective(goal),
    reflectionPrompt: copy.nextAfterCurrent,
    returnWith: copy.nextAfterCurrent,
    nextAfterCompletion: copy.nextAfterCurrent,
  };
  /*
  const nextCard = {
    ...card,
    cardId: `browser-preview-${isFlash ? "practice" : "flash"}-next-card`,
    type: isFlash ? "practice" as const : "flash" as const,
    title: isFlash ? copy.secondStage : language === "zh-CN" ? "闁搞儳鍋涚换鍌濄亹閹惧啿顤呴悗娑崇細缁″嫰鎯勯鐣屽灱闁汇劌瀚崣褔鏌ㄩ娆炬綈闁? : "Recall one key rule for the current learning goal",
  };
  };
  */
  const nextCard = {
    ...card,
    cardId: `browser-preview-${isFlash ? "practice" : "flash"}-next-card`,
    type: isFlash ? "practice" as const : "flash" as const,
    title: isFlash
      ? copy.secondStage
      : language === "zh-CN"
        ? "\u56de\u987e\u5f53\u524d\u5b66\u4e60\u76ee\u6807\u7684\u4e00\u6761\u5173\u952e\u89c4\u5219"
        : "Recall one key rule for the current learning goal",
  };
  const candidateType = cardType === "flash" ? "flash_candidate" : "practice_candidate";
  const nextCandidateType = nextCard.type === "flash" ? "flash_candidate" : "practice_candidate";
  const now = new Date().toISOString();

  return {
    task: {
      ...bootstrap.task,
      id: `browser-preview-training-${cardId}`,
      title: card.title,
      description: taskDescription,
      constraints: card.constraints,
      acceptanceCriteria: card.learnerDeliverables,
      nextActionLabel: copy.nextAfterCurrent,
    },
    memory: {
      ...bootstrap.memory,
      currentFocus: card.focusArea,
      reviewSummary: copy.planSummary,
    },
    coachingState: {
      ...bootstrap.coachingState,
      scenario: "task",
      answerMode: "guided",
      learnerSignal: "curious",
      summary: copy.taskReady(card.title),
      nextStep: card.suggestedWorkspaceAction || taskDescription,
      /*
      encouragement:
        language === "zh-CN"
          ? "闁稿繐鐗嗛悾顒勫箣閹邦垳绠瑰☉鎾亾鐎殿喚濮村畷閬嶆晬鐏炶棄鏅欓柛鎰暱閻ｉ箖寮伴姘剨闁圭鏅涢妵鍥╃磼閸愌呯槑闁肩厧鍟ú鍧楀Υ?
          : "Finish this one card before expanding the practice.",
      */
      encouragement:
        language === "zh-CN"
          ? "\u5148\u5b8c\u6210\u8fd9\u4e00\u5f20\u5361\uff0c\u518d\u6269\u5c55\u7ec3\u4e60\u3002"
          : "Finish this one card before expanding the practice.",
      updatedAt: now,
    },
    coachTurn: {
      ...bootstrap.coachTurn,
      scenario: "task",
      learnerSignal: "curious",
      summary: copy.taskReady(card.title),
      nextStep: card.suggestedWorkspaceAction || taskDescription,
      /*
      encouragement:
        language === "zh-CN"
          ? "闁稿繐鐗婃俊鍛婃交濞嗗繒鐐婇柛妞烩偓鍏呯驳閻庡湱鍎戠槐婵嬪礃瀹ュ洦鍩涚紓渚囧幒缁楀懏绋夐埀顒€顫㈤妷锝傚亾?
          : "Make this card concrete first, then continue.",
      */
      encouragement:
        language === "zh-CN"
          ? "\u5148\u628a\u8fd9\u5f20\u5361\u505a\u6210\u4e00\u4e2a\u53ef\u9a8c\u8bc1\u7684\u7ed3\u679c\uff0c\u518d\u7ee7\u7eed\u3002"
          : "Make this card concrete first, then continue.",
      activeTask: card.title,
      artifactKinds: ["task"],
      suggestedActionTypes: ["task"],
      backgroundMode: "embedded",
    },
    workspaceTrainingState: {
      ...bootstrap.workspaceTrainingState,
      workspaceId: "trainer-preview",
      selectedCardId: card.cardId,
      selectedCardType: card.type,
      selectedCardTitle: card.title,
      selectedCardStatus: "active",
      latestTrainingSubmode: cardType === "flash" ? "flash" : "practice",
      latestLearningFocusArea: card.focusArea,
      trainingCardCandidates: [card],
      activeTrainingCardRouting: {
        selectedCardId: card.cardId,
        selectedCard: card,
        whyThisCard: card.whyNow,
        fallbackAction: card.stuckRecovery,
        nextAfterCompletion: card.nextAfterCompletion,
        candidateCount: 1,
        eligibleCount: 1,
      },
      latestTrainingHandoff: {
        handoffId: `browser-preview-${card.cardId}-handoff`,
        candidateId: cardId,
        candidateType,
        targetKind: "training_card",
        targetId: cardId,
        continueIn: "training",
        acceptedInto: "training",
        handoffStatus: "accepted",
        handoffSummary: card.whyNow,
        cardType: card.type,
        cardTitle: card.title,
        learnerDeliverables: card.learnerDeliverables,
        verificationSteps: card.verificationSteps,
        successSignal: card.successSignal,
        returnWith: card.returnWith,
        nextAfterCompletion: card.nextAfterCompletion,
        judgedAt: now,
        sourceChain: ["browser-preview"],
      },
      latestTrainingNextHop: {
        candidateId: nextCard.cardId,
        candidateType: nextCandidateType,
        title: nextCard.title,
        summary: nextCard.problemStatement || nextCard.deliverable,
        whyNow: nextCard.whyNow,
        continueIn: "training",
        targetKind: "training_card",
        targetId: nextCard.cardId,
        acceptedInto: "training",
        status: "surfaced",
        cardType: nextCard.type,
        cardTitle: nextCard.title,
        returnSummary: nextCard.returnWith,
        judgedAt: now,
        sourceChain: ["browser-preview"],
      },
    },
  };
}

type PreviewTrainingCardContext = {
  cardId: string;
  cardTitle: string;
  cardType: "practice" | "flash";
  focusArea: string;
  handoffId: string;
  returnWith: string;
  nextAfterCompletion: string;
  sourceChain: string[];
};

type PreviewTrainingActionOptions = {
  eventType: string;
  summary: string;
  detail: string;
  selectedCardStatus: string;
  nextStep: string;
  coachScenario: "task" | "review";
  learnerSignal?: "steady" | "blocked" | "uncertain" | "curious";
  verifiedResult?: string;
  followup?: string;
  blocker?: string;
  partialProgress?: string;
  returnMode?: "result" | "blocker" | "verification_required" | "reflection_required" | "return_required";
  handoffStatus?: string;
  nextHopStatus?:
    | "created"
    | "surfaced"
    | "accepted"
    | "continued_in_chat"
    | "verification_required"
    | "reflection_required"
    | "return_required"
    | "dismissed"
    | "deferred"
    | "blocked"
    | "expired"
    | "archived";
  nextHopSummary?: string;
  nextHopWhyNow?: string;
  evidenceItem?: {
    id: string;
    summary: string;
    source: string;
    concepts: string[];
    outcome: string;
    confidence: number;
    timestamp: string;
    sourceCardId?: string;
    targetPlanStageId?: string;
  };
};

function resolvePreviewTrainingCardContext(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
): PreviewTrainingCardContext {
  const copy = resolveCopy(language);
  const trainingState = bootstrap.workspaceTrainingState ?? {};
  const candidate =
    trainingState.trainingCardCandidates?.find((item) => item.cardId === trainingState.selectedCardId) ??
    trainingState.activeTrainingCardRouting?.selectedCard ??
    trainingState.trainingCardCandidates?.[0];
  const goal = resolveBrowserPreviewGoal(bootstrap, language);
  const fallbackId = `browser-preview-${goal.replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "") || "training"}-card`;
  const cardId = trainingState.selectedCardId?.trim() || candidate?.cardId?.trim() || fallbackId;
  const cardTitle =
    trainingState.selectedCardTitle?.trim() ||
    candidate?.title?.trim() ||
    trainingState.latestTrainingHandoff?.cardTitle?.trim() ||
    copy.trainingOpenCurrentCard;
  const cardType = trainingState.selectedCardType ?? candidate?.type ?? "practice";
  const focusArea =
    trainingState.latestLearningFocusArea?.trim() ||
    candidate?.focusArea?.trim() ||
    goal;
  const handoffId =
    trainingState.latestTrainingHandoff?.handoffId?.trim() || `browser-preview-${cardId}-handoff`;
  const returnWith =
    trainingState.latestTrainingHandoff?.returnWith?.trim() || copy.trainingReturnToCoach;
  const nextAfterCompletion =
    trainingState.latestTrainingHandoff?.nextAfterCompletion?.trim() || copy.trainingReturnToCoach;
  const sourceChain = trainingState.latestTrainingHandoff?.sourceChain?.length
    ? [...trainingState.latestTrainingHandoff.sourceChain]
    : ["browser-preview"];

  return {
    cardId,
    cardTitle,
    cardType,
    focusArea,
    handoffId,
    returnWith,
    nextAfterCompletion,
    sourceChain,
  };
}

function buildPreviewEvidenceQueuePatch(
  bootstrap: BrowserPreviewBootstrap,
  evidenceItem: PreviewTrainingActionOptions["evidenceItem"],
): BrowserPreviewPatch {
  if (!evidenceItem) {
    return {};
  }
  const queue = bootstrap.memory?.evidenceQueue ?? {
    pending: [],
    deferred: [],
    adopted: [],
    rejected: [],
    totalCount: 0,
  };
  const pending = [
    {
      ...evidenceItem,
      sourceCardId: evidenceItem.sourceCardId,
      targetPlanStageId: evidenceItem.targetPlanStageId,
    },
    ...(queue.pending ?? []),
  ];
  return {
    memory: {
      ...bootstrap.memory,
      evidenceQueue: {
        pending,
        deferred: queue.deferred ?? [],
        adopted: queue.adopted ?? [],
        rejected: queue.rejected ?? [],
        totalCount:
          pending.length +
          (queue.deferred?.length ?? 0) +
          (queue.adopted?.length ?? 0) +
          (queue.rejected?.length ?? 0),
      },
    },
  };
}

function buildPreviewTrainingActionPatch(
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
  options: PreviewTrainingActionOptions,
): BrowserPreviewPatch {
  const uiCopy = resolveCopy(language);
  const card = resolvePreviewTrainingCardContext(bootstrap, language);
  const now = new Date().toISOString();
  const summary = `Browser-preview simulation: ${options.summary}`;
  const detail = `${options.detail} This only updates the local browser-preview fixture.`;
  const followup = options.followup ?? uiCopy.trainingReturnToCoach;
  const ledgerEntry = {
    eventId: `browser-preview-${options.eventType}-${now}`,
    eventType: options.eventType,
    selectedCardId: card.cardId,
    selectedCardType: card.cardType,
    selectedCardTitle: card.cardTitle,
    learnerDeliverables: bootstrap.workspaceTrainingState?.latestTrainingHandoff?.learnerDeliverables,
    verificationSteps: bootstrap.workspaceTrainingState?.latestTrainingHandoff?.verificationSteps,
    successSignal: bootstrap.workspaceTrainingState?.latestTrainingHandoff?.successSignal,
    returnWith: card.returnWith,
    nextAfterCompletion: card.nextAfterCompletion,
    fallbackAction: bootstrap.workspaceTrainingState?.latestTrainingHandoff?.fallbackAction,
    returnMode: options.returnMode,
    returnSummary: options.followup ?? followup,
    statusSummary: summary,
    statusDetail: detail,
    candidateTargetKind: "training_card",
    candidateTargetId: card.cardId,
    candidateAcceptedInto: "training",
    candidateType: "card_invocation" as const,
    candidateTitle: card.cardTitle,
    judgedAt: now,
    createdAt: now,
    sourceChain: ["browser-preview"],
  };

  return {
    ...buildPreviewEvidenceQueuePatch(bootstrap, options.evidenceItem),
    workspaceTrainingState: {
      ...bootstrap.workspaceTrainingState,
      workspaceId: "trainer-preview",
      latestTrainingHandoff: {
        ...bootstrap.workspaceTrainingState?.latestTrainingHandoff,
        handoffId: card.handoffId,
        candidateId: card.cardId,
        candidateType: "card_invocation",
        targetKind: "training_card",
        targetId: card.cardId,
        continueIn: "training",
        acceptedInto: "training",
        handoffStatus: options.handoffStatus ?? options.selectedCardStatus,
        handoffSummary: summary,
        cardType: card.cardType,
        cardTitle: card.cardTitle,
        returnWith: card.returnWith,
        nextAfterCompletion: card.nextAfterCompletion,
        returnMode: options.returnMode,
        returnSummary: options.followup ?? followup,
        judgedAt: now,
        sourceChain: card.sourceChain,
      },
      latestTrainingNextHop: {
        ...bootstrap.workspaceTrainingState?.latestTrainingNextHop,
        candidateId: card.cardId,
        candidateType:
          options.evidenceItem !== undefined
            ? "evidence_candidate"
            : card.cardType === "flash"
              ? "flash_candidate"
              : "practice_candidate",
        title: card.cardTitle,
        summary: options.nextHopSummary ?? detail,
        whyNow: options.nextHopWhyNow ?? summary,
        continueIn: "training",
        targetKind: "training_card",
        targetId: card.cardId,
        acceptedInto: "training",
        status: options.nextHopStatus ?? "accepted",
        cardType: card.cardType,
        cardTitle: card.cardTitle,
        returnMode: options.returnMode,
        returnSummary: options.followup ?? followup,
        judgedAt: now,
        sourceChain: ["browser-preview"],
      },
      latestTrainingSubmode: card.cardType === "flash" ? "flash" : "practice",
      latestLearningFocusArea: card.focusArea,
      latestLearningFollowup: followup,
      latestLearningVerifiedResult: options.verifiedResult ?? bootstrap.workspaceTrainingState?.latestLearningVerifiedResult,
      latestLearningBlocker: options.blocker ?? bootstrap.workspaceTrainingState?.latestLearningBlocker,
      latestLearningPartialProgress:
        options.partialProgress ?? bootstrap.workspaceTrainingState?.latestLearningPartialProgress,
      selectedCardId: card.cardId,
      selectedCardType: card.cardType,
      selectedCardTitle: card.cardTitle,
      selectedCardStatus: options.selectedCardStatus,
      trainingEventLedger: [...(bootstrap.workspaceTrainingState?.trainingEventLedger ?? []), ledgerEntry],
    },
    coachingState: {
      ...bootstrap.coachingState,
      scenario: options.coachScenario,
      answerMode: "guided",
      learnerSignal: options.learnerSignal ?? "curious",
      summary,
      nextStep: options.nextStep,
      encouragement: detail,
      updatedAt: now,
    },
    coachTurn: {
      ...bootstrap.coachTurn,
      scenario: options.coachScenario,
      learnerSignal: options.learnerSignal ?? "curious",
      summary,
      nextStep: options.nextStep,
      encouragement: detail,
      activeTask: card.cardTitle,
      artifactKinds: options.evidenceItem ? ["review"] : ["task"],
      suggestedActionTypes: options.evidenceItem ? ["review"] : ["task"],
      backgroundMode: "embedded",
    },
  };
}

function resourceForAction(
  bootstrap: BrowserPreviewBootstrap,
  action: WebviewAction,
): ResourceRecord | undefined {
  const resourceId =
    action.type === "resource/open"
      ? action.payload.resourceId
      : action.type === "command/execute" &&
          action.payload.commandId === trainerCommands.openResource &&
          action.payload.payload &&
          typeof action.payload.payload === "object" &&
          "resourceId" in action.payload.payload &&
          typeof action.payload.payload.resourceId === "string"
        ? action.payload.payload.resourceId
        : undefined;
  return resourceId ? bootstrap.resources?.find((resource) => resource.id === resourceId) : undefined;
}

type PreviewWorkspaceAdmissionStatus = "project-found" | "managed" | "browse" | "ignored";
type PreviewWorkspaceAdmissionState = PreviewWorkspaceAdmissionStatus | "root-missing";

const PREVIEW_WORKSPACE_MUTATION_COMMAND_IDS = new Set<string>([
  trainerCommands.generatePlan,
  trainerCommands.updatePlan,
  trainerCommands.nextTask,
  trainerCommands.indexResources,
  trainerCommands.trainingGenerateCard,
]);

function workspaceAdmissionDeletePatch(bootstrap: BrowserPreviewBootstrap): BrowserPreviewPatch {
  const workspace = bootstrap.memory.workspace ?? {};
  const admission = (workspace.trainerWorkspace ?? {}) as Partial<TrainerWorkspaceAdmission>;
  return {
    plan: {
      id: "",
      title: "",
      frozen: false,
      cadence: "",
      summary: "",
      stages: [],
    },
    task: {
      id: "",
      title: "",
      description: "",
      constraints: [],
      acceptanceCriteria: [],
      nextActionLabel: "",
    },
    workspaceTrainingState: {
      ...(bootstrap.workspaceTrainingState ?? {}),
      workspaceId: undefined,
      selectedCardId: undefined,
      selectedCardTitle: undefined,
    },
    memory: {
      ...bootstrap.memory,
      workspace: {
        ...workspace,
        workspaceId: undefined,
        projectContext: undefined,
        trainerWorkspace: {
          status: "project-found",
          rootPath: admission.rootPath,
          projectName: admission.projectName,
          projectPath: admission.projectPath,
        },
      },
    },
    hasFormalPlan: false,
  };
}

function workspaceAdmissionPatch(
  bootstrap: BrowserPreviewBootstrap,
  status: PreviewWorkspaceAdmissionStatus,
  copy: ReturnType<typeof resolveCopy>,
): BrowserPreviewPatch {
  const workspace = bootstrap.memory.workspace ?? {};
  const admission = (workspace.trainerWorkspace ?? {}) as Partial<TrainerWorkspaceAdmission>;
  const nextStep = previewWorkspaceAdmissionDetail(status, copy);
  const workspaceUnderstanding = bootstrap.memory.workspaceUnderstanding;

  return {
    memory: {
      ...bootstrap.memory,
      workspace: {
        ...workspace,
        trainerWorkspace: {
          ...admission,
          status,
          rootPath: admission.rootPath ?? "D:\\TrainerWorkspace",
          projectId: admission.projectId ?? "browser-preview-project",
          projectName: admission.projectName ?? "Preview project",
          projectPath: admission.projectPath ?? "D:\\TrainerWorkspace\\Projects\\browser-preview-project",
          updatedAt: "2026-07-18T00:00:00.000Z",
        },
      },
      ...(workspaceUnderstanding?.firstLookSummary
        ? {
            workspaceUnderstanding: {
              ...workspaceUnderstanding,
              firstLookSummary: {
                ...workspaceUnderstanding.firstLookSummary,
                recommendedNextStep: nextStep,
              },
            },
          }
        : {}),
    },
    ...(bootstrap.coachingState
      ? {
          coachingState: {
            ...bootstrap.coachingState,
            nextStep,
          },
        }
      : {}),
  };
}

function previewWorkspaceAdmissionStatus(
  bootstrap: BrowserPreviewBootstrap,
): PreviewWorkspaceAdmissionState | undefined {
  const status = bootstrap.memory?.workspace?.trainerWorkspace?.status;
  return status === "root-missing" ||
    status === "project-found" ||
    status === "managed" ||
    status === "browse" ||
    status === "ignored"
    ? status
    : undefined;
}

function previewWorkspaceAdmissionDetail(
  status: PreviewWorkspaceAdmissionState,
  copy: ReturnType<typeof resolveCopy>,
): string {
  switch (status) {
    case "root-missing":
      return copy.workspaceAdmissionRootMissingDetail;
    case "project-found":
      return copy.workspaceAdmissionProjectFoundDetail;
    case "managed":
      return copy.workspaceAdmissionManagedDetail;
    case "browse":
      return copy.workspaceAdmissionBrowseDetail;
    case "ignored":
      return copy.workspaceAdmissionIgnoredDetail;
  }
}

function previewWorkspaceAdmissionBlockedResult(
  status: PreviewWorkspaceAdmissionState | undefined,
  copy: ReturnType<typeof resolveCopy>,
): BrowserPreviewActionResult {
  return {
    tone: "info",
    message: previewWorkspaceAdmissionDetail(status ?? "root-missing", copy),
  };
}

function previewWorkspaceAdmissionTransition(
  commandId: string | undefined,
  bootstrap: BrowserPreviewBootstrap,
  copy: ReturnType<typeof resolveCopy>,
): BrowserPreviewActionResult | undefined {
  if (
    commandId !== trainerCommands.chooseTrainerWorkspaceRoot &&
    commandId !== trainerCommands.adoptWorkspaceProject &&
    commandId !== trainerCommands.browseWorkspaceProject &&
    commandId !== trainerCommands.ignoreWorkspaceProject &&
    commandId !== trainerCommands.deleteWorkspaceProject
  ) {
    return undefined;
  }

  const status = previewWorkspaceAdmissionStatus(bootstrap);
  if (commandId === trainerCommands.chooseTrainerWorkspaceRoot) {
    return status === undefined || status === "root-missing"
      ? {
          patch: workspaceAdmissionPatch(bootstrap, "project-found", copy),
          tone: "success",
          message: copy.workspaceAdmissionProjectFoundDetail,
        }
      : previewWorkspaceAdmissionBlockedResult(status, copy);
  }

  if (commandId === trainerCommands.deleteWorkspaceProject) {
    return status === "managed"
      ? {
          patch: workspaceAdmissionDeletePatch(bootstrap),
          tone: "success",
          message: copy.workspaceAdmissionProjectFoundDetail,
        }
      : previewWorkspaceAdmissionBlockedResult(status, copy);
  }

  if (status === "project-found" || status === "browse" || status === "ignored") {
    const targetStatus =
      commandId === trainerCommands.adoptWorkspaceProject
        ? "managed"
        : commandId === trainerCommands.browseWorkspaceProject
          ? "browse"
          : "ignored";
    if (targetStatus !== status) {
      return {
        patch: workspaceAdmissionPatch(bootstrap, targetStatus, copy),
        tone: "success",
        message: previewWorkspaceAdmissionDetail(targetStatus, copy),
      };
    }
  }

  return previewWorkspaceAdmissionBlockedResult(status, copy);
}

function previewWorkspaceMutationGate(
  commandId: string | undefined,
  bootstrap: BrowserPreviewBootstrap,
  copy: ReturnType<typeof resolveCopy>,
): BrowserPreviewActionResult | undefined {
  if (!commandId || !PREVIEW_WORKSPACE_MUTATION_COMMAND_IDS.has(commandId)) {
    return undefined;
  }

  const status = previewWorkspaceAdmissionStatus(bootstrap);
  return status && status !== "managed"
    ? previewWorkspaceAdmissionBlockedResult(status, copy)
    : undefined;
}

export function runBrowserPreviewAction(
  action: WebviewAction,
  bootstrap: BrowserPreviewBootstrap,
  language: ComposerLanguage,
): BrowserPreviewActionResult {
  const copy = copyFor(language);
  const uiCopy = resolveCopy(language);
  const workspaceCopy = resolveCopy(language);
  const commandId = commandIdForAction(action);

  const workspaceTransition = previewWorkspaceAdmissionTransition(
    commandId,
    bootstrap,
    workspaceCopy,
  );
  if (workspaceTransition) {
    return workspaceTransition;
  }

  const workspaceMutationBlock = previewWorkspaceMutationGate(commandId, bootstrap, workspaceCopy);
  if (workspaceMutationBlock) {
    return workspaceMutationBlock;
  }

  if (commandId === trainerCommands.generatePlan) {
    if (hasFormalPreviewPlan(bootstrap) && bootstrap.plan.frozen) {
      return { tone: "error", message: copy.planFrozen };
    }
    return {
      patch: buildGoalAwarePreviewPlanPatch(bootstrap, language),
      tone: "success",
      message: copy.generateSucceeded,
    };
  }

  if (commandId === trainerCommands.updatePlan) {
    const frozen =
      action.type === "plan/freeze"
        ? action.payload.frozen
        : action.type === "command/execute" &&
            action.payload.payload &&
            typeof action.payload.payload === "object" &&
            "frozen" in action.payload.payload
          ? Boolean(action.payload.payload.frozen)
          : true;
    const patch = updatePlanFreezePatch(bootstrap, language, frozen);
    if (!patch) {
      return { tone: "error", message: copy.missingPlan };
    }
    return {
      patch,
      tone: "success",
      message: frozen ? copy.planFrozen : copy.planResumed,
    };
  }

  if (commandId === trainerCommands.nextTask) {
    if (!hasFormalPreviewPlan(bootstrap)) {
      return { tone: "error", message: copy.missingPlan };
    }
    const task = buildPreviewTask(bootstrap.plan, language);
    return {
      patch: { task },
      tone: "success",
      message: copy.taskReady(task.title),
    };
  }

  if (commandId === trainerCommands.openResource) {
    const resource = resourceForAction(bootstrap, action);
    if (!resource) {
      return { tone: "error", message: copy.unsupported };
    }
    return {
      patch: {
        memory: {
          ...bootstrap.memory,
          selectedResourceDetail: resource,
        },
      },
      tone: "info",
      message: copy.resourceOpened(resource.title),
    };
  }

  if (commandId === trainerCommands.indexResources) {
    return {
      patch: refreshResourcesPatch(bootstrap),
      tone: "success",
      message: copy.resourcesRefreshed(bootstrap.resources?.length ?? 0),
    };
  }

  if (commandId === trainerCommands.trainingGenerateCard) {
    const patch = buildPreviewTrainingCardPatch(
      bootstrap,
      language,
      requestedPreviewTrainingCardType(action),
    );
    if (!patch) {
      return { tone: "error", message: copy.unsupported };
    }
    return {
      patch,
      tone: "success",
      message: copy.trainingCardReady,
    };
  }

  if (commandId === trainerCommands.evaluateCurrentFile) {
    return {
      tone: "error",
      message: copy.evaluateCurrentFileMissing,
    };
  }

  if (commandId === trainerCommands.trainingCardStatusTransition) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as { cardId?: string; newStatus?: string; reason?: string })
        : undefined;
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "training_card_status_transition",
        summary: `Move the training card to ${payload?.newStatus ?? "the next local status"}.`,
        detail: payload?.reason
          ? `Reason: ${payload.reason}.`
          : "The browser preview only updates its local training state.",
        selectedCardStatus: payload?.newStatus?.trim() || "in_progress",
        nextStep: uiCopy.trainingRecordStep,
        coachScenario: "task",
        learnerSignal: "curious",
        followup: uiCopy.trainingRecordStep,
        handoffStatus: payload?.newStatus?.trim() || "in_progress",
        nextHopStatus: "accepted",
        nextHopSummary: "The local card moved forward in the preview training flow.",
      }),
      tone: "success",
      message: "Browser-preview simulation: card status updated locally without touching a real workspace.",
    };
  }

  if (commandId === trainerCommands.trainingFlashcardAnswer) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as { cardId?: string; learnerAnswer?: string; answer?: string })
        : undefined;
    const answer = payload?.learnerAnswer?.trim() || payload?.answer?.trim() || "";
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "training_flashcard_answer",
        summary: "Record the flashcard answer in the local preview.",
        detail: "The browser preview did not call a real provider or update a real workspace.",
        selectedCardStatus: "answered",
        nextStep: uiCopy.trainingReturnToCoach,
        coachScenario: "task",
        learnerSignal: "curious",
        followup: uiCopy.trainingReturnToCoach,
        partialProgress: answer ? `Flashcard answer captured locally: ${answer}` : "Flashcard answer captured locally.",
        handoffStatus: "answered",
        nextHopStatus: "accepted",
        nextHopSummary: "The local flashcard answer is ready to return to Coach.",
      }),
      tone: "success",
      message: "Browser-preview simulation: flashcard answer recorded locally.",
    };
  }

  if (commandId === trainerCommands.trainingPracticeReturn) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as {
            cardId?: string;
            passed?: boolean;
            summary?: string;
            nextStep?: string;
            focusArea?: string;
          })
        : undefined;
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "training_practice_return",
        summary: "Return the verified practice result from the local preview.",
        detail: payload?.summary?.trim()
          ? `Practice return summary: ${payload.summary.trim()}`
          : "The browser preview only records the local return signal.",
        selectedCardStatus: payload?.passed ? "returned" : "verification_required",
        nextStep: uiCopy.trainingReturnToCoach,
        coachScenario: "review",
        learnerSignal: "curious",
        verifiedResult:
          payload?.passed === true
            ? payload?.summary?.trim() || "Browser-preview practice result verified locally."
            : undefined,
        followup: uiCopy.trainingReturnToCoach,
        returnMode: payload?.passed === true ? "result" : "verification_required",
        handoffStatus: payload?.passed === true ? "returned" : "verification_required",
        nextHopStatus: payload?.passed === true ? "accepted" : "verification_required",
        nextHopSummary: payload?.nextStep?.trim() || "Return the practice result to Coach.",
      }),
      tone: "success",
      message: "Browser-preview simulation: practice return recorded locally.",
    };
  }

  if (commandId === trainerCommands.trainingReflect) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as { cardId?: string; handoffId?: string; reflection?: string })
        : undefined;
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "training_reflect",
        summary: "Record the reflection step in the local preview.",
        detail: payload?.reflection?.trim()
          ? `Reflection captured locally: ${payload.reflection.trim()}`
          : "The browser preview only records a local reflection step.",
        selectedCardStatus: "reflected",
        nextStep: uiCopy.trainingReturnToCoach,
        coachScenario: "review",
        learnerSignal: "curious",
        followup: uiCopy.trainingReturnToCoach,
        partialProgress: payload?.reflection?.trim() || "Reflection captured locally.",
        returnMode: "return_required",
        handoffStatus: "ready_to_return",
        nextHopStatus: "return_required",
        nextHopSummary: "The local reflection step is ready to complete the return to Coach.",
      }),
      tone: "success",
      message: "Browser-preview simulation: reflection recorded locally.",
    };
  }

  if (commandId === trainerCommands.trainingReturn) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as { cardId?: string; handoffId?: string })
        : undefined;
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "training_return",
        summary: "Return the local training handoff to Coach.",
        detail: "The browser preview did not hand anything back to a real workspace.",
        selectedCardStatus: "returned",
        nextStep: uiCopy.trainingReturnToCoach,
        coachScenario: "review",
        learnerSignal: "curious",
        followup: uiCopy.trainingReturnToCoach,
        returnMode: "result",
        handoffStatus: "returned",
        nextHopStatus: "continued_in_chat",
        nextHopSummary: payload?.handoffId?.trim()
          ? `Local return completed for ${payload.handoffId.trim()}.`
          : "The local return completed in the preview fixture.",
      }),
      tone: "success",
      message: "Browser-preview simulation: return completed locally.",
    };
  }

  if (commandId === trainerCommands.evidenceEnqueue) {
    const payload =
      action.type === "command/execute" &&
      action.payload.payload &&
      typeof action.payload.payload === "object"
        ? (action.payload.payload as {
            waitingComposer?: boolean;
            source?: string;
            summary?: string;
            concepts?: string[];
            outcome?: string;
            sourceCardId?: string;
            targetPlanStageId?: string;
            confidence?: number;
          })
        : undefined;
    const waitingComposer = payload?.waitingComposer === true;
    const submitted = payload?.summary?.trim() ?? "";
    if (waitingComposer && !submitted) {
      return { tone: "info", message: copy.unsupported };
    }
    const now = new Date().toISOString();
    return {
      patch: buildPreviewTrainingActionPatch(bootstrap, language, {
        eventType: "evidence_enqueue",
        summary: "Queue evidence in the local browser preview.",
        detail:
          "The browser preview only updates a local evidence queue and does not create real evidence records.",
        selectedCardStatus: "evidence_queued",
        nextStep: uiCopy.trainingRecordStep,
        coachScenario: "review",
        learnerSignal: "curious",
        followup: uiCopy.trainingRecordStep,
        returnMode: "result",
        handoffStatus: "evidence_queued",
        nextHopStatus: "accepted",
        nextHopSummary: "The local evidence queue advanced in the preview fixture.",
        evidenceItem: {
          id: `browser-preview-evidence-${now}`,
          summary: waitingComposer
            ? submitted
            : payload?.summary?.trim() || "Browser-preview evidence queued locally.",
          source: waitingComposer
            ? "plan_runtime_verify"
            : payload?.source?.trim() || "browser_preview_simulation",
          concepts: Array.isArray(payload?.concepts) ? payload.concepts : [],
          outcome: waitingComposer ? "partial" : payload?.outcome?.trim() || "pass",
          confidence: waitingComposer
            ? 0
            : typeof payload?.confidence === "number"
              ? payload.confidence
              : 0.75,
          timestamp: now,
          sourceCardId: payload?.sourceCardId?.trim(),
          targetPlanStageId: payload?.targetPlanStageId?.trim(),
        },
      }),
      tone: "success",
      message: "Browser-preview simulation: evidence queued locally without creating a real evidence record.",
    };
  }

  return { tone: "info", message: copy.unsupported };
}
