---
name: organizar
description: "Organiza Desktop/Downloads/pastas soltas movendo (NUNCA deleta). Detecta clusters de trabalho ativo e preserva no Desktop. Manifest reversível. Args: [vazio | --apply | --auto | --undo | --where TEXTO | --status | --days N]."
allowed-tools: Bash, Read, Write
---

# /organizar — Organização sem destruição

Invoca a skill `organizar-maquina`. Move arquivos soltos pra estrutura clara, preserva trabalho ativo, manifest reversível.

## Argumentos

`$ARGUMENTS` recebido do usuário. Parseie:

| Forma | Significado |
|---|---|
| (vazio) | Dry-run: scan + plan + apresentar sumário pro Ricardo |
| `--apply` | Aplica plano mais recente (HIGH+MID, LOW vai pra _inbox) |
| `--apply --high-only` ou `--min-confidence 0.8` | Aplica só HIGH |
| `--auto` | scan + plan + apply --auto NUM ÚNICO TURNO (alerta antes!) |
| `--undo` | Reverte última run via manifest |
| `--undo TS` | Reverte run específica (manifest-{TS}.json) |
| `--where TEXTO` | Busca onde está agora um arquivo movido |
| `--status` | Sumário das runs feitas |
| `--days N` | Custom janela "ativo" (default 7) |
| `--source PATH` | Adiciona origem extra (pode repetir) |
| `--dest PATH` | Custom destino raiz |
| `--no-dedup` | Não detectar duplicatas (passa pro dryrun/auto) |
| `--no-trash` | Não detectar lixo (instaladores, vazios, parciais) |

> **Lixo e duplicatas (ligado por padrão):** o plano já marca instaladores re-baixáveis, downloads incompletos, arquivos/pastas vazios, build regenerável e cópias exatas. **Nada é apagado** — vão pra `~/Documents/Organizado/_REVISAR-EXCLUIR/` e o Ricardo exclui manualmente depois de conferir. Reversível com `--undo` até ele apagar.

## Workflow

### Modo padrão (sem args) — Dry-run + apresentação

1. Roda:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py dryrun
   ```
   (ou com `--days N`, `--source PATH` se passados)

2. Captura JSON da saída (após `---JSON---`). Extrai `plan_path`, `report_path`, `stats`.

3. Lê o relatório markdown (`report_path`) pra extrair lista de clusters ativos e top items LOW.

4. **Apresenta resumo CURTO pro Ricardo** (não despeja markdown inteiro):
   ```
   📦 Encontrei N arquivos/pastas pra organizar

   Status:
   - HIGH (aplicar direto): X
   - MID (aplicar c/ revisão): Y
   - LOW (vai pra _inbox/duvidas/): Z
   - Clusters ativos detectados: K
   - 🗑 Lixo + duplicatas: D itens ({tamanho}) → _REVISAR-EXCLUIR/

   🔥 Trabalho ativo (vão pro Desktop em pasta nomeada):
   - _ativo-{tema1}/ ({N} arq, mexido {Xd} atrás)
   - _ativo-{tema2}/ ...

   🗑 Pra você EXCLUIR depois (movo pra quarentena, NÃO apago):
   - {D} duplicatas + lixo, libera ~{tamanho}
   - destino: ~/Documents/Organizado/_REVISAR-EXCLUIR/

   ⚠️ Confiança baixa (vou jogar pra _inbox/duvidas/ pra você revisar):
   - arquivo1.pdf — sem heurística clara
   - arquivo2.zip — extensão compactada genérica

   Plano completo: {report_path}
   Plan JSON: {plan_path}

   Posso aplicar? Opções:
   - "vai" / "aplica" / "ok"  →  --apply (HIGH+MID, LOW vira _inbox)
   - "só HIGH"                →  --apply com --min-confidence 0.8
   - "ajusta X primeiro"      →  você diz o que mudar antes
   - "não"                    →  cancela, plano fica salvo
   ```

5. Espera resposta. Se OK, roda `apply` correspondente. Se não, deixa o plano salvo (Ricardo pode aplicar depois com `/organizar --apply`).

### Modo `--apply` — Aplicar plano salvo

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py apply [--min-confidence 0.8]
```

- Se passou `--high-only` ou `--min-confidence`, aplica só HIGH.
- Após apply, **anuncia onde está cada cluster ativo** (importante!) + total movido + comando de undo:
  ```
  ✅ Movi N arquivos.

  🔥 Clusters ativos pra você continuar trabalhando:
  - ~/Desktop/_ativo-cotezap-fix/  (5 arq)
  - ~/Desktop/_ativo-vinicius/      (3 arq)

  📁 Resto foi pra ~/Documents/Organizado/ (categorizado)

  🗑 Lixo + duplicatas ({D} itens, ~{tamanho}) foram pra:
     ~/Documents/Organizado/_REVISAR-EXCLUIR/
     → Confere e APAGA essa pasta pra recuperar o espaço. Eu não apago.

  Relatório completo: ~/Desktop/_organize-report-{ts}.md

  Pra reverter: /organizar --undo
  Pra achar arquivo: /organizar --where "nome"
  ```

### Modo `--auto` — Tudo num turno (cuidado!)

ANTES de rodar, AVISA Ricardo:
```
⚠️ Modo --auto pula a revisão do plano. Tudo será movido com base nas heurísticas
(LOW vai pra _inbox/duvidas/ automaticamente). Confirma? (sim/não)
```

Se sim:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py auto
```

Depois do apply, mostra anúncio igual ao modo `--apply`.

### Modo `--undo`

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py undo [--manifest TS]
```

Mostra resultado: N revertidos, erros se houver.

### Modo `--where TEXTO`

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py where "TEXTO"
```

Mostra resultado direto. Se nada achado, lembrar Ricardo que só funciona pra arquivos movidos pela skill (índice fica em `~/.local/share/organizar-maquina/activity-index.json`).

### Modo `--status`

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py status
```

Mostra direto.

## Princípios pra Claude orquestrar (não viole)

1. **Sempre dry-run primeiro**, mesmo se Ricardo pediu pra organizar. Apresenta antes de mover.
2. **Nunca rodar `--auto` sem alertar** explicitamente.
3. **Sempre destacar clusters ativos** no anúncio pós-apply — esses são onde Ricardo vai voltar a trabalhar.
4. **Sempre lembrar do `undo`** no final do anúncio.
5. **LOW confidence merece destaque** — nominalmente listar quem é (até 5 itens, depois "+N outros") pra ele decidir se quer ajustar antes ou deixar ir pro _inbox.
6. **Não despejar markdown inteiro** — relatório está no path, Ricardo abre se quiser ver detalhe.
7. **Se origem default vazia** (Desktop limpo já), avisar e parar.
8. **Quarentena NUNCA é apagada pela skill nem pelo Claude.** Lixo e duplicatas vão pra `_REVISAR-EXCLUIR/` e SÓ o Ricardo deleta, manualmente, fora da skill. Nunca rodar `rm` na quarentena, nunca oferecer pra apagar. O destaque no anúncio é pra ele saber onde recuperar espaço.

## Paths fixos a lembrar

- Script: `${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py`
- Skill: `${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/SKILL.md`
- Runtime: `~/.local/share/organizar-maquina/`
- Manifests: `~/.local/share/organizar-maquina/manifest-{ts}.json`
- Plans: `~/.local/share/organizar-maquina/plan-{ts}.json`
- Activity index: `~/.local/share/organizar-maquina/activity-index.json`
- Plan markdown: `~/Desktop/_organize-plan-{ts}.md`
- Report markdown: `~/Desktop/_organize-report-{ts}.md`
- Destino default: `~/Documents/Organizado/`
- Quarentena (lixo+dups, Ricardo apaga manual): `~/Documents/Organizado/_REVISAR-EXCLUIR/`
- Origens default: `~/Desktop`, `~/Downloads`, `/tmp/mac-sync`
