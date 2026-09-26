import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

/**
 * Tiny i18n for the local app: English (default) + Portuguese (Brazil).
 * - Strings live in the two dictionaries below, keyed the same way.
 * - `t("key", { n: 3 })` replaces `{n}` in the string.
 * - A missing Portuguese string falls back to English, so a screen is never blank.
 * The choice is remembered per browser; first visit follows the browser language.
 */
export type Lang = "en" | "pt";

const en = {
  // header / nav
  "nav.team": "Team",
  "nav.missions": "Missions",
  "nav.routines": "Routines",
  "nav.approvals": "Approvals",
  "header.command": "Command",
  "header.setup": "Setup",
  "header.today": "Today",
  "header.budgetReached": "Budget reached",
  "header.spendTitle": "Estimated model spend today",
  "header.language": "Language",

  // update banner + folder picker
  "update.ready":
    "An update is ready — double-click install.cmd (or “Eeze Agent – Update” in the Start menu), then reload this page.",
  "picker.browse": "Browse…",
  "picker.title": "Choose a folder",
  "picker.titleFile": "Choose a folder or one file",
  "picker.useFolder": "Use this folder",
  "picker.empty": "No sub-folders here.",
  "picker.media": "{n} photo/video file(s) in this folder",
  "picker.goBack": "pick another place on the left",

  // pairing (sign this browser in)
  "pair.title": "Sign in this browser",
  "pair.why":
    "Eeze runs only on this computer. Before a browser can see or approve anything, it has to be signed in once.",
  "pair.easyTitle": "Easiest: use the Eeze Agent shortcut",
  "pair.easyBody":
    "Double-click “Eeze Agent” on your Desktop (or in the Start menu). It opens Eeze right here, already signed in — nothing to copy or paste.",
  "pair.signingIn": "Signing you in…",
  "pair.otherWay": "No shortcut? Sign in with your access key instead",
  "pair.tokenLabel": "Access key",
  "pair.tokenWhere": "Open this file in Notepad, copy everything and paste it below:",
  "pair.tokenSafety":
    "The key stays on this computer — never share it or paste it anywhere else, including the public demo.",
  "pair.submit": "Sign in",
  "pair.pending": "Signing in…",
  "pair.failed": "That key did not match. Copy the whole file again and retry.",
  "pair.expired": "This link has already been used or expired. Double-click the Eeze Agent shortcut again.",
  "pair.unreachable":
    "Could not reach Eeze on this computer. Double-click the Eeze Agent shortcut — it starts Eeze if it is off.",
  "pair.duration": "This browser stays signed in for 30 days.",
  "pair.demo": "The public demo uses sample data and does not need signing in.",
  "pair.openDemo": "Open demo",

  // command bar
  "cmd.placeholder":
    "Describe what you want made (e.g. “rename my photos to trip001…”), or @mention an agent…",
  "cmd.newMission": "New mission",
  "cmd.draft": "Draft a mission: “{q}”",
  "cmd.draftFor": "Draft a mission: “{q}” for {agent}",
  "cmd.agents": "Agents",
  "cmd.navigate": "Navigate",
  "cmd.team": "Team dashboard",
  "cmd.missions": "Missions",
  "cmd.approvals": "Approval inbox",
  "cmd.empty": "No matching agent or action.",
  "cmd.demo": "In the real app this opens a mission draft.",

  // missions page
  "m.title": "Missions",
  "m.intro1": "Write the mission once. The agent drafts the plan,",
  "m.intro2": "you check it",
  "m.intro3": ", then run it. Risky steps still wait for you in Approvals.",
  "m.new": "New mission",
  "m.loadError": "Could not load missions.",
  "m.none": "No missions yet. Pick a recipe or write the goal, generate a draft, run it.",
  "m.neverRan": "never ran",
  "m.noPlan": "no plan",
  "m.name": "Name",
  "m.namePlaceholder": "Rename trip photos",
  "m.savedAs": "saved as: {id}",
  "m.kind": "Kind",
  "m.agent": "Agent",
  "m.schedule": "Schedule",
  "m.onDemand": "On demand",
  "m.daily": "Daily",
  "m.every": "Every…",
  "m.min": "min",
  "m.sched.onDemand": "on demand",
  "m.sched.daily": "daily at {at}",
  "m.sched.every": "every {n} min",
  "m.src.photo": "Photo (file or folder)",
  "m.src.video": "Clips (folder or one file)",
  "m.src.files": "Folder",
  "m.src.photoHint":
    "Paste a PNG/JPEG file path — or a folder of them. Quotes from “Copy as path” are fine. Your files are never modified.",
  "m.src.videoHint": "The folder with the clips/stills (they are read, never modified).",
  "m.src.filesHint":
    "The folder whose files will be renamed or organized. You see every change before it happens, and can undo it.",
  "m.recipes": "Start from a recipe",
  "m.recipesHint": "or write your own below — you can change everything",
  "m.needsFolder": "needs a folder",
  "m.step1": "1 — What should it do?",
  "m.step1Hint": "in your words (English or Portuguese); the plan is generated from this",
  "m.goalPlaceholder":
    "e.g. rename the photos in this folder to trip001, trip002… in the order they were taken",
  "m.generate": "Generate draft",
  "m.regenerate": "Regenerate draft",
  "m.writing": "Writing the plan…",
  "m.generateHint":
    "Runs on your local subscription — roughly 15 s, $0 spent. A refusal comes back with the reasons.",
  "m.goalFirst": "Write the goal first, then generate.",
  "m.regenWarn": "Regenerating replaces your current plan text.",
  "m.regenAnyway": "Regenerate anyway",
  "m.keepText": "Keep my text",
  "m.refused": "The writer refused: {msg}",
  "m.attempt": "attempt {n}: {err}",
  "m.rejected": "rejected",
  "m.refusedHint": "Nothing was saved and no fallback was used. Adjust the goal and try again.",
  "m.step2": "2 — The plan",
  "m.step2Hint": "this is exactly what will run",
  "m.edited": "edited",
  "m.advanced": "Advanced — {action} the exact plan",
  "m.advShow": "show and edit",
  "m.advHide": "hide",
  "m.planPlaceholder": "The plan appears here after “Generate draft”.",
  "m.valid": "Valid — the runner accepts this plan.",
  "m.problems": "{n} problem(s) found",
  "m.validate": "Validate",
  "m.checking": "Checking…",
  "m.save": "Save",
  "m.saveRun": "Save & run",
  "m.saveRunHint":
    "Checks the plan, saves it, then starts. It pauses once in Approvals before touching anything — tick “always allow” there to skip that next time.",
  "m.runAfterPlan": "Run appears once the mission has a plan.",
  "m.lastRun": "Last run:",
  "m.openRun": "open run",
  "m.decide": "decide it in Approvals",
  "m.runNow": "Run now",
  "m.remove": "Remove",
  "m.removeQ": "Remove “{name}”?",
  "m.cancel": "Cancel",
  "m.refresh": "Refresh",
  "m.toast.draft": "Draft written — nothing runs until you press Save & run.",
  "m.toast.saved": "Mission “{name}” saved.",
  "m.toast.valid": "Plan validated — the runner will accept this text.",
  "m.toast.fixFirst": "Fix the plan first — see the problems below it.",
  "m.toast.checkFail": "Could not check the plan: {msg}",
  "m.toast.started": "Mission started. Nothing risky runs without your click — check Approvals.",
  "m.toast.removed": "Mission removed.",
  "m.toast.kindCleared": "Plan cleared — a plan is written for one kind only.",
  "m.toast.kindClearedHint": "Generate a new draft for this kind.",
  "m.kind.3d": "3D render",
  "m.kind.video": "Video edit",
  "m.kind.photo": "Photo edit",
  "m.kind.task": "App task",
  "m.kind.files": "Files",
  "m.blurb.3d": "a Blender scene — still, turntable, .blend and .glb",
  "m.blurb.video": "cut, resize and join clips/stills into one video",
  "m.blurb.photo":
    "crop, resize, color adjustment and a twilight tint (it cannot yet select only the sky or one object)",
  "m.blurb.task": "a step list that drives an app (risky steps wait for you)",
  "m.blurb.files":
    "rename in sequence, organize into folders, find duplicates — preview first, undo anytime",
  "status.done": "done",
  "status.running": "running",
  "status.needs_approval": "needs approval",
  "status.error": "error",
  "status.interrupted": "interrupted",
  "status.denied": "denied",
  "status.abandoned": "dismissed",
  "status.expired": "expired",
  "status.budget_exceeded": "budget reached",

  // results / preview
  "r.before": "Before · your files (never modified)",
  "r.result": "Result",
  "r.working": "· working on it…",
  "r.runningEmpty": "The mission is running — results appear here as soon as they exist.",
  "r.waitingEmpty": "Waiting for your approval before anything runs.",
  "r.none": "No result files yet.",
  "r.steps": "See the {n} intermediate step(s)",
  "r.download": "Download",
  "r.openFull": "Open full size",
  "r.willDo": "Mission “{name}” will:",
  "r.onFiles": "On these files (read-only — results go to a new folder):",

  // files vertical
  "files.before": "Now",
  "files.after": "Will be",
  "files.showAll": "Show all {n}",
  "files.showLess": "Show less",
  "files.noDuplicates": "No duplicates found.",
  "files.previewChanges": "Preview: {n} of {total} file(s) will change — nothing changes until you approve.",
  "files.previewDuplicates": "Will compare {n} file(s) and list the identical ones. Nothing is deleted.",
  "files.conflicts": "Conflicts — the whole batch will be refused until these are fixed:",
  "files.nothingToChange": "Nothing to change — the names are already like that.",
  "files.undo": "Undo",
  "files.undone": "Undone — {n} file(s) are back as they were.",
  "files.failed": "Nothing changed: {error}",
  "files.duplicatesFound": "{n} group(s) of identical files:",
  "files.wasUndone": "{n} change(s) were undone.",
  "files.applied": "Done — {n} file(s) changed.",

  // approvals
  "a.title": "Approvals",
  "a.intro":
    "Risky steps wait here. Approving resumes the paused run from the exact step; denying stops it cleanly. Nothing executes without your click.",
  "a.loadError": "We couldn't load the approval queue.",
  "a.loadErrorHint": "Is the Eeze API running on this machine?",
  "a.tech": "Technical details (exact command)",
  "a.grantMission": "Always allow this mission to run (24h) — revocable below",
  "a.grantTask": "Always allow this class for this task (24h) — creates a revocable grant",
  "a.legacy":
    "This older approval cannot resume safely, so it can't be approved. Dismiss it to unblock its routine — nothing will run — and the next run asks again.",
  "a.noGrant":
    "This step changes your files, so it is approved one batch at a time (no “always allow”).",
  "a.dismiss": "Dismiss",
  "a.approve": "Approve & resume",
  "a.deny": "Deny",
  "a.empty": "Nothing is waiting on you.",
  "a.emptyHint": "When a run reaches a risky step, it pauses and appears here.",
  "a.recent": "Recent decisions",
  "a.grants": "Active grants",
  "a.forTask": "for {task}",
  "a.forAgent": "for this agent",
  "a.expires": "· expires {at}",
  "a.noExpiry": "· no expiry",
  "a.revoke": "Revoke",
  "a.toast.dismissed": "Dismissed — nothing ran. Its routine will schedule again normally.",
  "a.toast.denied": "Denied — the run stops cleanly and never executes this step.",
  "a.toast.resuming": "Approved — the run is resuming now.",
  "a.toast.approved": "Approved.",
  "a.toast.revoked": "Grant revoked — the next run of that class will ask again.",
  "risk.read": "Read",
  "risk.write_local": "Write (local)",
  "risk.external_send": "Send",
  "risk.install_exec": "Runs a program",
  "risk.destructive": "Changes your files",
  "risk.system": "System",
} as const;

export type MessageKey = keyof typeof en;

const pt: Partial<Record<MessageKey, string>> = {
  "nav.team": "Equipe",
  "nav.missions": "Missões",
  "nav.routines": "Rotinas",
  "nav.approvals": "Aprovações",
  "header.command": "Comando",
  "header.setup": "Configurar",
  "header.today": "Hoje",
  "header.budgetReached": "Limite atingido",
  "header.spendTitle": "Gasto estimado com modelos hoje",
  "header.language": "Idioma",

  "update.ready":
    "Há uma atualização pronta — dê dois cliques no install.cmd (ou “Eeze Agent – Atualizar” no menu Iniciar) e recarregue esta página.",
  "picker.browse": "Escolher…",
  "picker.title": "Escolha uma pasta",
  "picker.titleFile": "Escolha uma pasta ou um arquivo",
  "picker.useFolder": "Usar esta pasta",
  "picker.empty": "Nenhuma subpasta aqui.",
  "picker.media": "{n} foto(s)/vídeo(s) nesta pasta",
  "picker.goBack": "escolha outro lugar à esquerda",
  "pair.title": "Conecte este navegador",
  "pair.why":
    "O Eeze roda só neste computador. Antes de um navegador ver ou aprovar qualquer coisa, ele precisa ser conectado uma vez.",
  "pair.easyTitle": "Mais fácil: use o atalho Eeze Agent",
  "pair.easyBody":
    "Dê dois cliques em “Eeze Agent” na Área de Trabalho (ou no menu Iniciar). Ele abre o Eeze aqui, já conectado — nada para copiar ou colar.",
  "pair.signingIn": "Conectando…",
  "pair.otherWay": "Sem o atalho? Conecte com a sua chave de acesso",
  "pair.tokenLabel": "Chave de acesso",
  "pair.tokenWhere": "Abra este arquivo no Bloco de Notas, copie tudo e cole abaixo:",
  "pair.tokenSafety":
    "A chave fica neste computador — nunca compartilhe nem cole em outro lugar, nem na demo pública.",
  "pair.submit": "Conectar",
  "pair.pending": "Conectando…",
  "pair.failed": "A chave não confere. Copie o arquivo inteiro de novo e tente outra vez.",
  "pair.expired": "Este link já foi usado ou expirou. Dê dois cliques no atalho Eeze Agent de novo.",
  "pair.unreachable":
    "Não foi possível falar com o Eeze neste computador. Dê dois cliques no atalho Eeze Agent — ele liga o Eeze se estiver desligado.",
  "pair.duration": "Este navegador fica conectado por 30 dias.",
  "pair.demo": "A demo pública usa dados de exemplo e não precisa de conexão.",
  "pair.openDemo": "Abrir demo",
  "cmd.placeholder":
    "Descreva o que você quer (ex.: “renomear minhas fotos para viagem001…”) ou @mencione um agente…",
  "cmd.newMission": "Nova missão",
  "cmd.draft": "Criar rascunho de missão: “{q}”",
  "cmd.draftFor": "Criar rascunho de missão: “{q}” para {agent}",
  "cmd.agents": "Agentes",
  "cmd.navigate": "Ir para",
  "cmd.team": "Painel da equipe",
  "cmd.missions": "Missões",
  "cmd.approvals": "Caixa de aprovações",
  "cmd.empty": "Nenhum agente ou ação encontrado.",
  "cmd.demo": "No app de verdade isto abre um rascunho de missão.",

  "m.title": "Missões",
  "m.intro1": "Escreva a missão uma vez. O agente monta o plano,",
  "m.intro2": "você confere",
  "m.intro3": " e manda rodar. Passos arriscados continuam esperando por você em Aprovações.",
  "m.new": "Nova missão",
  "m.loadError": "Não foi possível carregar as missões.",
  "m.none": "Nenhuma missão ainda. Escolha uma receita ou escreva o objetivo, gere o rascunho e rode.",
  "m.neverRan": "nunca rodou",
  "m.noPlan": "sem plano",
  "m.name": "Nome",
  "m.namePlaceholder": "Renomear fotos da viagem",
  "m.savedAs": "salvo como: {id}",
  "m.kind": "Tipo",
  "m.agent": "Agente",
  "m.schedule": "Agenda",
  "m.onDemand": "Quando eu pedir",
  "m.daily": "Todo dia",
  "m.every": "A cada…",
  "m.min": "min",
  "m.sched.onDemand": "quando eu pedir",
  "m.sched.daily": "todo dia às {at}",
  "m.sched.every": "a cada {n} min",
  "m.src.photo": "Foto (arquivo ou pasta)",
  "m.src.video": "Clipes (pasta ou um arquivo)",
  "m.src.files": "Pasta",
  "m.src.photoHint":
    "Cole o caminho de uma foto PNG/JPEG — ou de uma pasta com fotos. Pode colar com as aspas do “Copiar como caminho”. Seus arquivos nunca são alterados.",
  "m.src.videoHint": "A pasta com os clipes/imagens (são lidos, nunca alterados).",
  "m.src.filesHint":
    "A pasta cujos arquivos serão renomeados ou organizados. Você vê cada mudança antes de acontecer e pode desfazer.",
  "m.recipes": "Comece por uma receita",
  "m.recipesHint": "ou escreva a sua abaixo — dá para mudar tudo",
  "m.needsFolder": "precisa de uma pasta",
  "m.step1": "1 — O que deve ser feito?",
  "m.step1Hint": "com as suas palavras (português ou inglês); o plano é gerado a partir disto",
  "m.goalPlaceholder":
    "ex.: renomeie as fotos desta pasta para viagem001, viagem002… na ordem em que foram tiradas",
  "m.generate": "Gerar rascunho",
  "m.regenerate": "Gerar de novo",
  "m.writing": "Escrevendo o plano…",
  "m.generateHint":
    "Roda na sua assinatura local — cerca de 15 s, US$ 0. Se recusar, os motivos aparecem aqui.",
  "m.goalFirst": "Escreva o objetivo primeiro, depois gere.",
  "m.regenWarn": "Gerar de novo substitui o texto atual do plano.",
  "m.regenAnyway": "Gerar mesmo assim",
  "m.keepText": "Manter meu texto",
  "m.refused": "O escritor recusou: {msg}",
  "m.attempt": "tentativa {n}: {err}",
  "m.rejected": "recusada",
  "m.refusedHint": "Nada foi salvo e nenhuma alternativa foi usada. Ajuste o objetivo e tente de novo.",
  "m.step2": "2 — O plano",
  "m.step2Hint": "é exatamente isto que vai rodar",
  "m.edited": "editado",
  "m.advanced": "Avançado — {action} o plano exato",
  "m.advShow": "ver e editar",
  "m.advHide": "esconder",
  "m.planPlaceholder": "O plano aparece aqui depois de “Gerar rascunho”.",
  "m.valid": "Válido — o executor aceita este plano.",
  "m.problems": "{n} problema(s) encontrado(s)",
  "m.validate": "Conferir",
  "m.checking": "Conferindo…",
  "m.save": "Salvar",
  "m.saveRun": "Salvar e rodar",
  "m.saveRunHint":
    "Confere o plano, salva e inicia. Pausa uma vez em Aprovações antes de mexer em qualquer coisa — marque “sempre permitir” lá para pular isso da próxima vez.",
  "m.runAfterPlan": "O botão de rodar aparece quando a missão tiver um plano.",
  "m.lastRun": "Última execução:",
  "m.openRun": "abrir execução",
  "m.decide": "decidir em Aprovações",
  "m.runNow": "Rodar agora",
  "m.remove": "Remover",
  "m.removeQ": "Remover “{name}”?",
  "m.cancel": "Cancelar",
  "m.refresh": "Atualizar",
  "m.toast.draft": "Rascunho pronto — nada roda até você clicar em Salvar e rodar.",
  "m.toast.saved": "Missão “{name}” salva.",
  "m.toast.valid": "Plano conferido — o executor aceita este texto.",
  "m.toast.fixFirst": "Corrija o plano primeiro — veja os problemas abaixo dele.",
  "m.toast.checkFail": "Não foi possível conferir o plano: {msg}",
  "m.toast.started": "Missão iniciada. Nada arriscado roda sem o seu clique — veja Aprovações.",
  "m.toast.removed": "Missão removida.",
  "m.toast.kindCleared": "Plano apagado — cada plano serve para um tipo só.",
  "m.toast.kindClearedHint": "Gere um rascunho novo para este tipo.",
  "m.kind.3d": "Render 3D",
  "m.kind.video": "Vídeo",
  "m.kind.photo": "Foto",
  "m.kind.task": "Tarefa em app",
  "m.kind.files": "Arquivos",
  "m.blurb.3d": "uma cena no Blender — imagem, animação girando, .blend e .glb",
  "m.blurb.video": "cortar, redimensionar e juntar clipes/imagens em um vídeo",
  "m.blurb.photo":
    "recortar, redimensionar, ajustar cor e um tom de crepúsculo (ainda não seleciona só o céu ou um objeto)",
  "m.blurb.task": "uma lista de passos que opera um app (passos arriscados esperam por você)",
  "m.blurb.files":
    "renomear em sequência, organizar em pastas, achar duplicadas — prévia antes, desfazer quando quiser",
  "status.done": "concluída",
  "status.running": "rodando",
  "status.needs_approval": "aguardando aprovação",
  "status.error": "erro",
  "status.interrupted": "interrompida",
  "status.denied": "negada",
  "status.abandoned": "descartada",
  "status.expired": "expirada",
  "status.budget_exceeded": "limite de gasto atingido",

  "r.before": "Antes · seus arquivos (nunca alterados)",
  "r.result": "Resultado",
  "r.working": "· trabalhando…",
  "r.runningEmpty": "A missão está rodando — os resultados aparecem aqui assim que existirem.",
  "r.waitingEmpty": "Aguardando a sua aprovação antes de qualquer coisa rodar.",
  "r.none": "Ainda não há arquivos de resultado.",
  "r.steps": "Ver as {n} etapa(s) intermediária(s)",
  "r.download": "Baixar",
  "r.openFull": "Abrir em tamanho real",
  "r.willDo": "A missão “{name}” vai:",
  "r.onFiles": "Nestes arquivos (só leitura — o resultado vai para uma pasta nova):",

  "files.before": "Agora",
  "files.after": "Vai ficar",
  "files.showAll": "Mostrar todos os {n}",
  "files.showLess": "Mostrar menos",
  "files.noDuplicates": "Nenhuma duplicada encontrada.",
  "files.previewChanges":
    "Prévia: {n} de {total} arquivo(s) vão mudar — nada muda até você aprovar.",
  "files.previewDuplicates": "Vai comparar {n} arquivo(s) e listar os idênticos. Nada é apagado.",
  "files.conflicts": "Conflitos — o lote inteiro será recusado até isto ser resolvido:",
  "files.nothingToChange": "Nada a mudar — os nomes já estão assim.",
  "files.undo": "Desfazer",
  "files.undone": "Desfeito — {n} arquivo(s) voltaram como estavam.",
  "files.failed": "Nada mudou: {error}",
  "files.duplicatesFound": "{n} grupo(s) de arquivos idênticos:",
  "files.wasUndone": "{n} mudança(s) foram desfeitas.",
  "files.applied": "Pronto — {n} arquivo(s) alterado(s).",

  "a.title": "Aprovações",
  "a.intro":
    "Passos arriscados esperam aqui. Aprovar continua a execução exatamente de onde parou; negar encerra sem executar. Nada roda sem o seu clique.",
  "a.loadError": "Não foi possível carregar as aprovações.",
  "a.loadErrorHint": "O serviço do Eeze está rodando neste computador?",
  "a.tech": "Detalhes técnicos (comando exato)",
  "a.grantMission": "Sempre permitir esta missão (24h) — dá para revogar abaixo",
  "a.grantTask": "Sempre permitir esta classe para esta tarefa (24h) — revogável",
  "a.legacy":
    "Esta aprovação antiga não pode continuar com segurança, então não pode ser aprovada. Descarte para destravar a rotina — nada vai rodar — e a próxima execução pede de novo.",
  "a.noGrant":
    "Este passo altera seus arquivos, então é aprovado um lote de cada vez (sem “sempre permitir”).",
  "a.dismiss": "Descartar",
  "a.approve": "Aprovar e continuar",
  "a.deny": "Negar",
  "a.empty": "Nada esperando por você.",
  "a.emptyHint": "Quando uma execução chega a um passo arriscado, ela pausa e aparece aqui.",
  "a.recent": "Decisões recentes",
  "a.grants": "Permissões ativas",
  "a.forTask": "para {task}",
  "a.forAgent": "para este agente",
  "a.expires": "· expira {at}",
  "a.noExpiry": "· sem validade",
  "a.revoke": "Revogar",
  "a.toast.dismissed": "Descartada — nada rodou. A rotina volta a ser agendada normalmente.",
  "a.toast.denied": "Negada — a execução para sem executar este passo.",
  "a.toast.resuming": "Aprovada — a execução está continuando.",
  "a.toast.approved": "Aprovada.",
  "a.toast.revoked": "Permissão revogada — a próxima execução desta classe vai pedir de novo.",
  "risk.read": "Leitura",
  "risk.write_local": "Grava (local)",
  "risk.external_send": "Envia",
  "risk.install_exec": "Roda um programa",
  "risk.destructive": "Altera seus arquivos",
  "risk.system": "Sistema",
};

const DICTS: Record<Lang, Partial<Record<MessageKey, string>>> = { en, pt };
const STORAGE_KEY = "eeze-lang";

type Vars = Record<string, string | number>;
export type Translate = (key: MessageKey, vars?: Vars) => string;

function format(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}

function translator(lang: Lang): Translate {
  return (key, vars) => format(DICTS[lang][key] ?? en[key] ?? key, vars);
}

function initialLang(): Lang {
  if (typeof window === "undefined") return "en";
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "pt") return saved;
  } catch {
    /* storage blocked: fall through to the browser language */
  }
  return (navigator.language || "").toLowerCase().startsWith("pt") ? "pt" : "en";
}

const I18nContext = createContext<{ lang: Lang; setLang: (lang: Lang) => void; t: Translate }>({
  lang: "en",
  setLang: () => undefined,
  t: translator("en"),
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  useEffect(() => setLangState(initialLang()), []);
  useEffect(() => {
    if (typeof document !== "undefined") document.documentElement.lang = lang === "pt" ? "pt-BR" : "en";
  }, [lang]);
  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* not persisted; fine */
    }
  }, []);
  const value = useMemo(() => ({ lang, setLang, t: translator(lang) }), [lang, setLang]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}

export function useT(): Translate {
  return useContext(I18nContext).t;
}

/** Language switch for the header: EN | PT. */
export function LanguageToggle() {
  const { lang, setLang, t } = useI18n();
  return (
    <div
      role="group"
      aria-label={t("header.language")}
      className="flex items-center rounded-md border border-border p-0.5 text-[11px] font-medium"
    >
      {(["en", "pt"] as const).map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => setLang(option)}
          aria-pressed={lang === option}
          className={`rounded px-1.5 py-0.5 uppercase transition-colors ${
            lang === option ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
