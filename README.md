# macos-organizador

Plugin Claude Code que organiza a máquina **sem destruir contexto de trabalho**.
Move, nunca apaga. O que parece lixo vai pra quarentena e **só o humano deleta**.

## Instalar

```bash
/plugin marketplace add ~/dev/macos-organizador
/plugin install macos-organizador@macos-organizador
/reload-plugins
```

## Usar

```bash
/organizar                 # dry-run: scan + plano + resumo (nada é movido)
/organizar --apply         # aplica HIGH+MID; LOW vai pra _inbox
/organizar --apply --high-only
/organizar --undo          # reverte a última run via manifesto
/organizar --where "nome"  # onde foi parar um arquivo movido
/organizar --status        # sumário das runs
```

O engine também roda direto:

```bash
python3 skills/organizar-maquina/scripts/organize.py dryrun
python3 skills/organizar-maquina/scripts/organize.py apply --auto
python3 skills/organizar-maquina/scripts/organize.py undo
```

## Invariantes

1. **Nunca apaga.** Lixo e duplicatas vão pra `_REVISAR-EXCLUIR/`; a exclusão é manual.
2. **Reversível.** Toda run escreve um manifesto (`~/.local/share/organizar-maquina/`).
3. **Casa existente vence pasta nova.** Antes de criar `Organizado/`, procura a casa canônica
   que já existe (`~/Documents/Midia`, `Notas-e-Rascunhos`, `Metricas`, `Hackintosh`, o `.env`
   do projeto, a pasta de backups...).
4. **Trabalho ativo fica acessível.** Cluster recente não é arquivado.
5. **Baixa confiança não decide.** Vai pra `_inbox/` pra revisão humana.

## Corrigido nesta versão

**Duplicata escolhia o canônico errado.** `pick_canonical` rankeava por
`(cara de cópia, mais antigo, path curto)` e nunca olhava o conteúdo. Como
`louise-prompt.md.pdf` (markdown com extensão mentirosa) era o mais antigo, ele
vencia e o `.md` correto ia pra quarentena.

Agora **extensão honesta é o primeiro critério**: `ext_lies()` compara os magic bytes
com o que a extensão promete (`.pdf` sem `%PDF-`, `.png` sem assinatura PNG, etc.).
Arquivo cuja extensão mente nunca sobrevive a um irmão idêntico bem nomeado.

## Limitações conhecidas (validadas em produção, 2026-06-14)

Uma limpeza real de 36 itens expôs estes defeitos. **Ainda não corrigidos** no engine
(foram contornados à mão naquela run). Roadmap da v0.2:

| # | Defeito | Evidência |
|---|---|---|
| 1 | **iCloud**: mover pra fora da área sincronizada trava no `fileproviderd` (o rename vira cópia via XPC, sem I/O visível). Mover *dentro* do iCloud é rename instantâneo. | Um move de 14 GB pendurou o processo; o mesmo item levou 0,01 s ao permanecer dentro do iCloud. |
| 2 | **"Pasta vazia"** olha só `du`, ignora subpastas nomeadas com intenção. | `Energia Solar` e `Skills Polymarket` iam pra fila de exclusão. |
| 3 | **"Instalador re-baixável"** assume que todo `.dmg` se re-baixa. | Os builds do KRIT são privados e esta máquina não compila: eram irreproduzíveis. |
| 4 | **Casa canônica**: força `~/Documents/Organizado/` em vez de procurar a casa que já existe. | Mídia, notas e métricas já tinham casa; o plano criava estrutura paralela. |
| 5 | **Segredos** não são detectados; iriam pra quarentena, que fica no iCloud. | 4 arquivos de credencial viva no Desktop sincronizado. |
| 6 | **Tamanho** subestimado (soma rasa, não `du` real). | Snapshots reportados 2× a 14× menores. |

## Conflito com a instalação antiga

Este plugin substitui a skill solta. Depois de instalar, remova (você mesmo, o
plugin nunca apaga nada):

```
~/.claude/skills/organizar-maquina/
~/.claude/commands/organizar.md
```

Senão o comando `/organizar` e a skill ficam duplicados.

## Estrutura

```
.claude-plugin/{plugin,marketplace}.json
commands/organizar.md
skills/organizar-maquina/{SKILL.md,scripts/organize.py}
```
