# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento [SemVer](https://semver.org/lang/pt-BR/).

## [0.1.1] — 2026-07-09

### Adicionado
- **Marker `.organizador-cockpit`**: diretório que contém esse arquivo nunca entra no plano.
  Protege pastas-cockpit do usuário (docs de organização, cockpits de projeto como o Cote.Zap)
  de serem capturadas pelo scan — antes exigia editar o plan JSON a cada run.

## [0.1.0] — 2026-07-09

### Adicionado
- **Empacotamento como plugin Claude Code.** A skill `organizar-maquina` e o comando
  `/organizar`, que viviam soltos em `~/.claude/`, viraram um plugin instalável com
  `.claude-plugin/{plugin,marketplace}.json`.
- Engine determinístico (`organize.py`) com `scan`, `plan`, `apply`, `undo`, `where`,
  `status`, `dryrun`, `auto` e manifesto reversível.

### Corrigido
- **`pick_canonical` escolhia a duplicata errada.** O rank era
  `(cara de cópia, mais antigo, path curto)` e ignorava o conteúdo, então um arquivo
  com extensão mentirosa vencia por ser mais antigo. Caso real: `louise-prompt.md.pdf`
  (markdown, sem header `%PDF-`) sobreviveu e o `.md` correto foi pra quarentena.
  Agora `ext_lies()` compara magic bytes com a extensão e **extensão honesta é o
  primeiro critério de rank**. Coberto por 3 testes (fix + 2 regressões).
- Paths hardcoded (`~/.claude/skills/...`) removidos: o engine referencia a si mesmo
  via `SELF = os.path.abspath(__file__)` e a doc usa `${CLAUDE_PLUGIN_ROOT}`. Assim as
  mensagens de ajuda apontam pro caminho real, instalado como plugin ou não.

### Conhecido (roadmap 0.2)
- Não entende iCloud: mover pra fora da área sincronizada trava no `fileproviderd`.
- "Pasta vazia" ignora subpastas nomeadas; "instalador re-baixável" assume que todo
  `.dmg` se re-baixa (falso para builds privados).
- Não procura a casa canônica já existente antes de criar `~/Documents/Organizado/`.
- Não detecta segredos (credenciais iriam pra quarentena, que fica no iCloud).
- Tamanho de diretório subestimado (soma rasa em vez de `du` real).
