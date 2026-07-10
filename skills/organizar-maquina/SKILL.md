---
name: organizar-maquina
description: Organiza Desktop/Downloads/pastas soltas movendo (NUNCA deleta) pra estrutura clara em ~/Documents/Organizado/. Detecta clusters de trabalho ATIVO via mtime + correlação e preserva no Desktop em pasta `_ativo-{tema}/`. Detecta LIXO (instaladores re-baixáveis, downloads incompletos, vazios, build regenerável) e DUPLICATAS exatas (arquivos por hash completo, pastas por assinatura) e move pra quarentena `_REVISAR-EXCLUIR/` pra o humano excluir manual — nunca apaga. Manifest reversível, baixa confiança vai pra `_inbox/duvidas/`. Invocada quando usuário diz 'organizar máquina', 'organizar arquivos', 'limpar desktop', 'arrumar downloads', 'eliminar lixo', 'remover duplicatas', '/organizar', 'arquivos espalhados', 'tô perdido nessa bagunça', ou pede pra estruturar pastas sem perder nada.
---

# Organizar Máquina

Organiza arquivos soltos sem destruir contexto de trabalho. Move, nunca deleta. Detecta o que é trabalho ativo e preserva continuidade.

## Princípios invioláveis

1. **Zero deleção.** Toda operação é `mv`. Colisão de nome resolve via comparação de hash (duplicata exata) ou renomeio com timestamp.
2. **Manifest reversível.** Cada `apply` escreve `~/.local/share/organizar-maquina/manifest-{ts}.json` com mapping origem→destino. `undo` reverte 100%.
3. **Trabalho ativo preservado.** Cluster com 2+ arquivos modificados nos últimos N dias (default 7) vai pra `~/Desktop/_ativo-{tema}/` — fica no Desktop, agrupado por tema, fluxo continua.
4. **Dúvida sinaliza, não chuta.** Confiança < 0.50 vai pra `_inbox/duvidas/` em vez de adivinhar destino. Ricardo revisa manualmente.
5. **Relatório explica onde está cada coisa.** Markdown em `~/Desktop/_organize-report-{ts}.md` agrupado por pasta destino + reversão em uma linha.
6. **Lixo e duplicata NÃO são apagados — vão pra quarentena.** A skill identifica o que é lixo/cópia e MOVE pra `~/Documents/Organizado/_REVISAR-EXCLUIR/`. **Quem deleta é o Ricardo**, manualmente, depois de conferir. Reversível via `undo` até ele apagar. Esse é o jeito de "eliminar" sem violar a regra de zero deleção.

## Quando esta skill é invocada

- "organiza minha máquina"
- "limpa meu desktop"
- "arruma essa bagunça de downloads"
- "tô perdido com esses arquivos espalhados"
- `/organizar` (slash command que delega aqui)

## Fluxo padrão (dry-run primeiro)

```
1. SCAN     → enumera Desktop + Downloads + /tmp/mac-sync
2. CLASSIFY → cada arquivo: categoria + confiança + razão
3. CLUSTER  → agrupa por (origem + janela 6h temporais)
4. PLAN     → propõe destinos, gera ~/Desktop/_organize-plan-{ts}.md
5. APRESENTA SUMÁRIO PRO RICARDO (HIGH/MID/LOW + clusters ativos)
6. ESPERA OK
7. APPLY    → move + manifest + ~/Desktop/_organize-report-{ts}.md
8. ANUNCIA  → onde está cada coisa, como reverter
```

## Subcomandos do script

Caminho fixo: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py`

```bash
# Dry-run (default — só gera plano, não move nada).
# Por padrão JÁ detecta lixo e duplicatas (vão pro plano como quarentena).
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py dryrun [--days N] [--source PATH]

# Desligar detecção de lixo e/ou duplicatas (se quiser só organizar)
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py dryrun --no-dedup --no-trash

# Aplica plano mais recente
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py apply              # HIGH+MID, LOW vai pra _inbox
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py apply --auto       # tudo (LOW também vai pra _inbox)
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py apply --min-confidence 0.8  # só HIGH

# Tudo de uma vez (cuidado — não dá tempo de revisar)
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py auto

# Reverter última run (ou específica via --manifest)
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py undo
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py undo --manifest manifest-20260426-235959.json

# Onde está agora um arquivo movido?
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py where "transcricao-vinicius"

# Status das runs
python3 ${CLAUDE_PLUGIN_ROOT}/skills/organizar-maquina/scripts/organize.py status
```

## Comportamento esperado da skill (Claude orquestrando)

Quando invocada, Claude DEVE:

1. **Sempre rodar dryrun primeiro**, mesmo se Ricardo pediu "auto". Apresentar sumário antes de mover.
2. **Apresentar resumo curto** (não despejar o markdown inteiro):
   - Total de itens + breakdown HIGH/MID/LOW
   - Lista de clusters ATIVOS (esses ele provavelmente está trabalhando agora — destacar!)
   - Itens LOW destacados (precisam revisão)
   - Path do plano e do relatório (Ricardo abre no Finder se quiser detalhe)
3. **Para clusters ativos**: explicar que vão pra `~/Desktop/_ativo-{tema}/` pra preservar fluxo. Citar o tema.
4. **Para itens LOW**: listar nominalmente. "Achei N arquivos com baixa confiança: X, Y, Z. Por padrão vão pra `_inbox/duvidas/` pra você revisar manualmente. Quer que eu force destino específico em algum?"
5. **Pedir confirmação inline** antes de aplicar. Padrão: "aplica HIGH+MID, LOW vai pra _inbox?". Ricardo responde "vai" / "só HIGH" / "ajusta X primeiro".
6. **Após apply**: avisar onde está cada cluster ativo (importante porque ele vai voltar a trabalhar logo). Mencionar comando `where` e `undo`.
7. **Nunca** rodar `auto` sem alertar antes que vai pular a revisão.
8. **Quarentena (lixo + duplicatas)**: no sumário, dizer quantos itens e quanto espaço vão pra `_REVISAR-EXCLUIR/` e que **o Ricardo apaga manualmente** depois de conferir. Após apply, apontar o caminho da pasta e o total recuperável. NUNCA oferecer pra apagar a quarentena — só o Ricardo faz isso, fora da skill.

## Estrutura de destino padrão

```
~/Documents/Organizado/
├── projetos/
│   ├── easyquote/
│   ├── quotezap/
│   ├── sixclaw-ceo/
│   ├── sixclaw-chupacabra/
│   ├── sixquasar/
│   ├── avafly/
│   ├── lupe/
│   └── {outros descobertos}/
├── apresentacoes/
├── contratos/
│   ├── {ano}/
│   ├── notas-fiscais/{ano}/
│   └── boletos/{ano}/
├── referencias/
│   ├── pdfs/{ano}/
│   ├── documentos/{ano}/
│   ├── planilhas/{ano}/
│   ├── notas/
│   ├── briefings/
│   ├── transcricoes/{ano-mes}/
│   ├── curriculos/
│   ├── configs/
│   └── livros/
├── codigo/
│   ├── python/
│   ├── typescript/
│   ├── javascript/
│   ├── scripts/
│   ├── sql/
│   └── outros/
├── midia/
│   ├── imagens/{ano}/
│   ├── videos/{ano}/
│   ├── audio/{ano}/
│   └── design/
├── _quickshares/{ano-mes}/      # screenshots, IMG_*, fotos rápidas
├── _inbox/
│   ├── duvidas/                  # confiança < 0.50, requer revisão
│   ├── diretorios/               # pastas pequenas sem categoria clara
│   ├── arquivos-compactados/
│   └── instaladores/
└── _REVISAR-EXCLUIR/             # QUARENTENA — Ricardo apaga manualmente
    ├── duplicatas/               # cópias exatas (o original fica no lugar)
    └── lixo/
        ├── instaladores/         # .dmg/.pkg/.iso re-baixáveis
        ├── downloads-incompletos/ # .crdownload/.part/.tmp
        ├── vazios/               # arquivos 0 byte + pastas vazias
        └── build-regeneravel/    # node_modules/dist/.next soltos

~/Desktop/
├── _ativo-{tema-slug}/           # clusters de trabalho ativo (≤ 7d, 2+ arq)
├── _organize-plan-{ts}.md        # plano dry-run
└── _organize-report-{ts}.md      # relatório pós-apply
```

## Decisões de classificação

**Sinais de alta confiança (HIGH ≥ 0.80)**:
- Keyword de projeto no nome (`easyquote`, `quotezap`, `sixclaw`, `chupacabra`, `polybrain`, `vinicius rezende`)
- Padrão de nome explícito (`Contrato*.pdf`, `Captura de Tela*`, `*.dmg`)
- Extensão única (`.mp3`, `.mov`, `.mp4`)

**Sinais de média confiança (MID 0.50–0.80)**:
- Extensão com múltiplos destinos plausíveis (`.pdf`, `.docx`, `.xlsx`)
- Diretório sem keyword clara mas com >5 arquivos

**Sinais de baixa confiança (LOW < 0.50)**:
- Sem heurística aplicável
- Diretório pequeno sem keyword
- `.md`/`.txt` genérico

## Detecção de cluster ativo

Cluster = grupo de arquivos da mesma pasta origem modificados em janela de 6h.

ATIVO = avg_age_days ≤ 7 (configurável via `--days`) E tem 2+ arquivos.

Tema do cluster = longest common prefix dos nomes, ou keyword de projeto encontrada nos nomes, ou "diversos".

Singletons (1 arquivo) NÃO viram pasta `_ativo-` — vão pra estrutura permanente normal mesmo se recentes (não compensa criar pasta pra 1 arquivo).

## Detecção de lixo e duplicatas (quarentena, não deleção)

Ligada por padrão. Desliga com `--no-trash` / `--no-dedup`. **Nada é apagado** — itens detectados são MOVIDOS pra `~/Documents/Organizado/_REVISAR-EXCLUIR/` e o Ricardo decide o que excluir.

**Duplicatas (precisão alta, zero falso-positivo de conteúdo):**
- **Arquivos**: agrupa por tamanho idêntico, confirma com **sha256 do arquivo inteiro** (não só 64KB). Só vira duplicata com hash 100% igual.
- **Pastas**: assinatura = hash do conjunto `{caminho-relativo:tamanho}` de todos os arquivos. Duas pastas com assinatura igual são idênticas em layout (pega casos tipo as pastas WhatsApp extraídas repetidas).
- **Canônico mantido** (o que NÃO é movido): nome sem cara de cópia > mais antigo (original) > caminho mais curto. As demais cópias vão pra `_REVISAR-EXCLUIR/duplicatas/`.

**Lixo (regras de alta precisão, conservador):**
| Regra | Bucket |
|---|---|
| `.crdownload`/`.part`/`.download`/`.partial`/`.tmp`/`.crswap` | `lixo/downloads-incompletos/` |
| Arquivo 0 byte / pasta vazia | `lixo/vazios/` |
| `node_modules`/`dist`/`build`/`.next`/`__pycache__`/`.venv`/`venv`/`target`/... soltos no topo | `lixo/build-regeneravel/` |
| Instalador `.dmg`/`.pkg`/`.iso`/`.msi`/`.exe` (cruza com /Applications p/ dizer se já instalado) | `lixo/instaladores/` |

Na dúvida, NÃO marca como lixo — segue fluxo normal de organização. Foto/documento pessoal nunca é classificado como lixo automaticamente.

## Aviso de continuidade pós-mover

Após `apply`, Claude deve narrar pro Ricardo (resumo, não a lista inteira):

```
Movi N arquivos. Os clusters ativos que você provavelmente vai querer continuar mexendo:

🔥 ~/Desktop/_ativo-cotezap-fix/  (5 arquivos, mexido 2d atrás)
🔥 ~/Desktop/_ativo-vinicius/      (3 arquivos, mexido 1d atrás)

Resto foi pra ~/Documents/Organizado/ por categoria. Relatório completo em
~/Desktop/_organize-report-{ts}.md (origem→destino).

Pra reverter qualquer coisa: `/organizar --undo`
Pra achar arquivo X: `/organizar --where X`
```

## Interação com regras Ricardo

- **NUNCA exclui** — alinhado com regra "Nao apagar arquivos — pedir pro usuario fazer manualmente"
- **Manifest reversível** — alinhado com regra "Backup OBRIGATORIO antes de mudanca"
- **Dryrun first** — alinhado com regra "NUNCA mudancas grandes sem planejamento aprovado"
- **Confiança baixa = pergunta** — alinhado com regra "ESCUTAR O USUARIO" e "Verificar ANTES de negar"

## Limites conhecidos

- Não desce em subdiretórios das origens. Top-level only. Diretório no Desktop vai como unidade atômica (vai inteiro pra `projetos/{slug}` ou `_inbox/diretorios/`).
- Não classifica arquivos > 5MB por conteúdo (só por nome+extensão). Performance.
- Hash de classificação trunca em 64KB. **Mas a dedup usa sha256 do arquivo INTEIRO** (só entre arquivos de tamanho idêntico, pra ser rápido) — duplicata confirmada é byte-a-byte, sem falso-positivo.
- Assinatura de pasta (dedup de diretório) só vale pra pastas com ≤ 5000 arquivos (acima disso o walk é parcial e a dedup é pulada por segurança).
- macOS bundles (`.app`, `.bundle`, `.framework`) tratados como arquivo (não desce dentro).
- Não toca em `~/Library/`, `.git/`, `node_modules/`, `.claude/`, `.Trash/`, `.cache/`, `.npm/`.
- Cross-filesystem move funciona via `shutil.move` (copy+remove). Se origem em volume diferente do destino, demora mais.

## Customização

Pra mudar o destino raiz: `--dest ~/MeuOrganizado/`
Pra adicionar fonte extra: `--source ~/SomePath/` (pode repetir)
Pra mudar janela ativo: `--days 14`

Heurísticas de classificação ficam em `scripts/organize.py` nas constantes `NAME_HEURISTICS` e `PROJECT_KEYWORDS`. Adicionar entradas conforme aprende novos projetos.
