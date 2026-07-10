#!/usr/bin/env python3
"""organize.py — skill organizar-maquina

Subcomandos:
  scan      enumera fontes e coleta metadata
  plan      gera plano de movimentação (dry-run, sem mover nada)
  apply     executa plano (move arquivos, escreve manifest reversível)
  undo      reverte última run (ou específica via --manifest PATH)
  where     busca onde está agora um arquivo originalmente em PATH
  status    sumário das runs feitas
  dryrun    atalho: scan + plan
  auto      atalho: scan + plan + apply --auto

Princípios:
  - NUNCA deleta. Só move (com hash compare em colisão).
  - Manifest JSON reversível por run.
  - Trabalho ATIVO (mtime ≤ N dias + cluster com 2+ arq) fica em ~/Desktop/_ativo-{tema}/.
  - Confiança LOW vai pra _inbox/duvidas/ (revisão manual).
  - Activity-index mantém mapping path-original → path-atual pra consulta `where`.
  - LIXO e DUPLICATAS NÃO são apagados: vão pra _REVISAR-EXCLUIR/ pra o humano
    excluir manualmente depois de conferir. Reversível como qualquer move.
    Desativável com --no-dedup / --no-trash.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Caminho absoluto deste script (usado nas mensagens de ajuda).
# Funciona instalado como plugin ou como skill solta.
SELF = os.path.abspath(__file__)


# ============================================================
# Config
# ============================================================

HOME = Path.home()
DEFAULT_SOURCES = [HOME / "Desktop", HOME / "Downloads", Path("/tmp/mac-sync")]
DEFAULT_DEST_ROOT = HOME / "Documents" / "Organizado"
ACTIVE_CLUSTER_DIR = HOME / "Desktop"
RUNTIME_DIR = HOME / ".local" / "share" / "organizar-maquina"
REPORT_DIR = HOME / "Desktop"

DEFAULT_DAYS_ACTIVE = 7
HIGH_CONF = 0.80
MID_CONF = 0.50

# Quarentena: lixo e duplicatas vão pra cá pra revisão/exclusão MANUAL do humano.
# A skill NUNCA apaga — só move pra esta pasta sob o destino raiz.
REVIEW_DIR_NAME = "_REVISAR-EXCLUIR"

# Extensões de download incompleto / temporário (lixo de alta precisão).
PARTIAL_EXTS = {".crdownload", ".part", ".download", ".partial", ".crswap", ".tmp"}

# Instaladores re-baixáveis (o app reinstala do zero; o arquivo não guarda dado).
INSTALLER_EXTS = {".dmg", ".pkg", ".iso", ".msi", ".exe"}

# Diretórios de build/deps regeneráveis quando aparecem SOLTOS no topo de uma origem.
BUILD_ARTIFACT_DIRS = {
    "node_modules", ".next", "dist", "build", "__pycache__", ".venv", "venv",
    "target", ".turbo", ".parcel-cache", ".gradle", ".pytest_cache", ".mypy_cache",
}

# Nome com cara de cópia — desempata qual exemplar é o canônico a MANTER na dedup.
COPY_HINT_RE = re.compile(r"(?i)(c[oó]pia|\bcopy\b|\(\d+\)|[ _-]\d+(\.[^.]+)?$)")

IGNORE_NAME_PATTERNS = [
    r"^\.DS_Store$",
    r"^\.Spotlight-V100$",
    r"^\.Trashes$",
    r"^\.fseventsd$",
    r"^\.localized$",
    r"^\.com\.apple",
    r"^Icon\r?$",
    r"^_organize-(plan|report)-",
    r"^_ativo-",
    r"^\.TemporaryItems$",
]

IGNORE_PATH_FRAGMENTS = [
    "/.git/", "/node_modules/", "/.claude/", "/Library/",
    "/.Trash/", "/.npm/", "/.cache/", "/.local/share/Trash/",
    "/.pyenv/", "/.cargo/", "/.bun/", "/.nvm/", "/.rbenv/",
    "/.gradle/", "/.docker/", "/.colima/",
]

# (regex padrão de nome, destino template, confiança)
NAME_HEURISTICS = [
    (r"(?i)^contrato\b.*\.(pdf|docx)$", "contratos/{ano}", 0.95),
    (r"(?i)\bcontrato\b.*\.(pdf|docx)$", "contratos/{ano}", 0.85),
    (r"(?i)^(nfe?|nota[_\s-]?fiscal)[_\s-]?\d", "contratos/notas-fiscais/{ano}", 0.85),
    (r"(?i)\b(boleto|fatura)\b.*\.pdf$", "contratos/boletos/{ano}", 0.85),
    (r"(?i)^(captura de tela|screen[\s_-]?shot|screenshot)", "_quickshares/{ano-mes}", 0.95),
    (r"(?i)^IMG_\d{4,}\.(jpg|jpeg|png|heic)$", "midia/imagens/{ano}", 0.7),
    (r"(?i)^DSC[_-]?\d{3,}", "midia/imagens/{ano}", 0.85),
    (r"(?i)\bapresenta(c|ç)[aã]o\b.*\.(pptx|key|pdf)$", "apresentacoes", 0.85),
    (r"(?i)\bproposta\b.*\.(pdf|docx)$", "apresentacoes", 0.7),
    (r"(?i)\bbriefing\b.*\.(pdf|docx|md)$", "referencias/briefings", 0.8),
    (r"(?i)\b(curriculo|currículo|resume|cv)\b.*\.(pdf|docx)$", "referencias/curriculos", 0.85),
    (r"(?i)\b(transcri(c|ç)ão|transcript)\b", "referencias/transcricoes/{ano-mes}", 0.85),
    (r"(?i)\.(mov|mp4|mkv|webm|avi|m4v)$", "midia/videos/{ano}", 0.85),
    (r"(?i)\.(mp3|wav|flac|m4a|aac|ogg|opus)$", "midia/audio/{ano}", 0.85),
    (r"(?i)\.(jpg|jpeg|png|heic|gif|tiff|webp|bmp|raw|cr2|nef)$", "midia/imagens/{ano}", 0.6),
    (r"(?i)\.(svg|ai|psd|sketch|fig|xd)$", "midia/design", 0.8),
    (r"(?i)\.(xlsx|xls|csv|ods|numbers)$", "referencias/planilhas/{ano}", 0.7),
    (r"(?i)\.pdf$", "referencias/pdfs/{ano}", 0.5),
    (r"(?i)\.(docx|doc|odt|rtf|pages)$", "referencias/documentos/{ano}", 0.5),
    (r"(?i)\.(md|txt|markdown)$", "referencias/notas", 0.4),
    (r"(?i)\.(json|yaml|yml|toml|ini|env|conf)$", "referencias/configs", 0.5),
    (r"(?i)\.(py|ipynb)$", "codigo/python", 0.7),
    (r"(?i)\.(ts|tsx)$", "codigo/typescript", 0.7),
    (r"(?i)\.(js|jsx|mjs)$", "codigo/javascript", 0.7),
    (r"(?i)\.(sh|bash|zsh|fish)$", "codigo/scripts", 0.7),
    (r"(?i)\.(sql)$", "codigo/sql", 0.7),
    (r"(?i)\.(go|rs|rb|php|java|kt|swift|c|cpp|h)$", "codigo/outros", 0.6),
    (r"(?i)\.(zip|tar|gz|tgz|bz2|7z|rar|xz)$", "_inbox/arquivos-compactados", 0.6),
    (r"(?i)\.(dmg|pkg|app|deb|rpm|exe|msi)$", "_inbox/instaladores", 0.85),
    (r"(?i)\.(epub|mobi|azw3)$", "referencias/livros", 0.85),
]

# Keywords pra detectar projeto (no nome OU conteúdo).
# Tupla: (keyword_lower, destination, conf_se_no_nome, conf_se_no_conteudo)
PROJECT_KEYWORDS = [
    ("easyquote", "projetos/easyquote", 0.92, 0.75),
    ("quotezap", "projetos/quotezap", 0.92, 0.75),
    ("cote.zap", "projetos/quotezap", 0.92, 0.75),
    ("cotezap", "projetos/quotezap", 0.92, 0.75),
    ("avafly", "projetos/avafly", 0.90, 0.70),
    ("openclaw", "projetos/openclaw", 0.90, 0.70),
    ("sixclaw-ceo", "projetos/sixclaw-ceo", 0.92, 0.75),
    ("sixclaw_ceo", "projetos/sixclaw-ceo", 0.92, 0.75),
    ("sixclaw ceo", "projetos/sixclaw-ceo", 0.92, 0.75),
    ("chupacabra", "projetos/sixclaw-chupacabra", 0.90, 0.70),
    ("polybrain", "projetos/sixclaw-chupacabra/polybrain", 0.90, 0.70),
    ("vinicius rezende", "projetos/sixclaw-ceo", 0.85, 0.65),
    ("agente lupe", "projetos/lupe", 0.90, 0.70),
    ("six quasar", "projetos/sixquasar", 0.85, 0.60),
    ("sixquasar", "projetos/sixquasar", 0.85, 0.60),
    ("sixclaw", "projetos/sixclaw", 0.80, 0.60),
    ("compras_ids", "projetos/easyquote", 0.85, 0.85),
    ("amux", "projetos/amux", 0.80, 0.55),
    ("claude-peers", "projetos/claude-peers", 0.85, 0.65),
    ("ricardo landim", "pessoal", 0.55, 0.45),
]


# ============================================================
# Helpers
# ============================================================

def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_runtime():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


COCKPIT_MARKER = ".organizador-cockpit"


def is_ignored(path: Path) -> bool:
    name = path.name
    s = str(path)
    if any(re.match(p, name) for p in IGNORE_NAME_PATTERNS):
        return True
    if any(frag in s for frag in IGNORE_PATH_FRAGMENTS):
        return True
    # Pasta-cockpit do usuário (docs de organização, CLAUDE.md da sessão etc.):
    # um dir marcado com .organizador-cockpit nunca entra no plano.
    if path.is_dir() and (path / COCKPIT_MARKER).exists():
        return True
    return False


def safe_slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.lower()).strip("-")
    return s[:max_len] or "geral"


def file_hash(path: Path, n: int = 65536) -> str:
    """sha256 truncado dos primeiros 64KB (rápido o suficiente pra dedup)."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            chunk = f.read(n)
            h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return ""


def full_file_hash(path: Path, chunk: int = 1 << 20) -> str:
    """sha256 do arquivo INTEIRO. Usado só pra confirmar duplicata quando dois
    arquivos têm o mesmo tamanho — evita falso-positivo do hash de 64KB."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except Exception:
        return ""


def file_sample(path: Path, n: int = 4096) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(n).decode("utf-8", errors="ignore").lower()
    except Exception:
        return ""


def file_type_descriptor(path: Path) -> str:
    try:
        out = subprocess.check_output(
            ["/usr/bin/file", "-b", str(path)],
            stderr=subprocess.DEVNULL, timeout=5
        )
        return out.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def fmt_size(n: int) -> str:
    f = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if f < 1024:
            return f"{f:.1f}{unit}"
        f /= 1024
    return f"{f:.1f}PB"


def longest_common_prefix(strs: list) -> str:
    if not strs:
        return ""
    s = min(strs)
    e = max(strs)
    for i, c in enumerate(s):
        if c != e[i]:
            return s[:i]
    return s


# ============================================================
# Scan
# ============================================================

def scan_path(p: Path) -> Optional[dict]:
    """Coleta metadata de arquivo OU diretório top-level."""
    try:
        st = p.stat()
    except (FileNotFoundError, PermissionError, OSError):
        return None

    is_dir = p.is_dir()
    name = p.name
    ext = p.suffix.lower()

    # Bundles macOS são tratados como arquivo atômico
    bundle_exts = {".app", ".bundle", ".framework", ".kext", ".plugin", ".docset"}

    if is_dir and ext not in bundle_exts:
        size = 0
        file_count = 0
        latest_mtime = st.st_mtime
        sig_parts = []
        complete = True
        try:
            for child in p.rglob("*"):
                try:
                    if child.is_file():
                        cs = child.stat()
                        size += cs.st_size
                        file_count += 1
                        if cs.st_mtime > latest_mtime:
                            latest_mtime = cs.st_mtime
                        sig_parts.append(f"{child.relative_to(p)}:{cs.st_size}")
                        if file_count > 5000:
                            complete = False  # assinatura parcial → não confiável p/ dedup
                            break
                except (FileNotFoundError, PermissionError, OSError):
                    continue
        except (FileNotFoundError, PermissionError, OSError):
            complete = False
        mtime = latest_mtime
        # Assinatura de conteúdo: hash do conjunto {relpath:tamanho}. Só vale se o
        # walk foi completo; duas pastas com mesma assinatura são idênticas em layout.
        if complete and file_count > 0:
            sig_parts.sort()
            dir_sig = hashlib.sha256(
                "\n".join(sig_parts).encode("utf-8", "ignore")
            ).hexdigest()[:24]
        else:
            dir_sig = ""
    else:
        size = st.st_size
        mtime = st.st_mtime
        file_count = 1
        dir_sig = ""

    age_days = (datetime.now().timestamp() - mtime) / 86400
    h = file_hash(p) if not is_dir or ext in bundle_exts else ""
    desc = file_type_descriptor(p) if (not is_dir or ext in bundle_exts) else "directory"

    return {
        "path": str(p.resolve()),
        "name": name,
        "size": size,
        "mtime": mtime,
        "ctime": st.st_ctime,
        "atime": st.st_atime,
        "ext": ext,
        "is_dir": is_dir and ext not in bundle_exts,
        "file_count": file_count,
        "hash": h,
        "dir_sig": dir_sig,
        "file_type": desc,
        "age_days": age_days,
    }


def scan_sources(sources: list) -> list:
    entries = []
    for src in sources:
        src = Path(src).expanduser()
        if not src.exists() or not src.is_dir():
            continue
        try:
            for child in src.iterdir():
                if is_ignored(child):
                    continue
                e = scan_path(child)
                if e:
                    e["source_root"] = str(src)
                    entries.append(e)
        except (PermissionError, FileNotFoundError, OSError):
            continue
    return entries


# ============================================================
# Classify
# ============================================================

TEXT_EXT = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".ts", ".js",
            ".tsx", ".jsx", ".sh", ".html", ".css", ".csv", ".log", ".sql",
            ".env", ".conf", ".ini", ".toml"}


def classify(entry: dict) -> dict:
    name = entry["name"]
    ext = entry["ext"]
    is_dir = entry["is_dir"]
    sample = ""

    if not is_dir and entry["size"] < 5_000_000 and ext in TEXT_EXT:
        try:
            sample = file_sample(Path(entry["path"]))
        except Exception:
            pass

    candidates = []
    signals = {}

    ano = datetime.fromtimestamp(entry["mtime"]).year
    ano_mes = datetime.fromtimestamp(entry["mtime"]).strftime("%Y-%m")
    fmt_vars = {"ano": ano, "ano-mes": ano_mes}

    # 1. Project keywords (highest signal)
    haystack_name = name.lower()
    for kw, dest, conf_name, conf_content in PROJECT_KEYWORDS:
        if kw in haystack_name:
            candidates.append((dest, conf_name, f"keyword '{kw}' no nome"))
            signals["project_keyword"] = kw
            break
        elif sample and kw in sample:
            candidates.append((dest, conf_content, f"keyword '{kw}' no conteúdo"))
            signals["project_keyword"] = kw
            break

    # 2. Diretório top-level → projeto
    if is_dir and not candidates:
        slug = safe_slug(name, 30)
        if entry["file_count"] > 5:
            candidates.append((f"projetos/{slug}", 0.55, f"diretório com {entry['file_count']} arquivos"))
            signals["dir_treatment"] = "projeto"
        else:
            candidates.append((f"_inbox/diretorios/{slug}", 0.4, f"diretório pequeno ({entry['file_count']} arq)"))
            signals["dir_treatment"] = "inbox"

    # 3. Name heuristics
    for pattern, dest_template, conf in NAME_HEURISTICS:
        if re.search(pattern, name):
            try:
                dest = dest_template.format(**fmt_vars) if "{" in dest_template else dest_template
            except (KeyError, IndexError):
                dest = dest_template
            candidates.append((dest, conf, f"padrão de nome match"))
            signals["name_pattern"] = pattern
            break

    # 4. Best wins
    if candidates:
        candidates.sort(key=lambda c: -c[1])
        cat, conf, reason = candidates[0]
    else:
        cat, conf, reason = ("_inbox", 0.25, "sem heurística aplicável")

    is_quickshare = bool(re.match(
        r"(?i)^(captura de tela|screen[\s_-]?shot|screenshot|IMG_\d|DSC[_-]?\d)",
        name
    ))

    return {
        "category": cat,
        "confidence": conf,
        "reason": reason,
        "is_quickshare": is_quickshare,
        "signals": signals,
    }


# ============================================================
# Cluster
# ============================================================

def cluster_entries(entries: list, days_active: int) -> list:
    """Cluster por (source_dir, time_proximity 6h)."""
    entries = sorted(entries, key=lambda e: (e["source_root"], e["mtime"]))

    clusters = []
    current = []
    last_mtime = None
    last_dir = None

    for e in entries:
        if not current:
            current = [e]
        elif (e["source_root"] == last_dir and
              abs(e["mtime"] - last_mtime) < 6 * 3600):
            current.append(e)
        else:
            clusters.append(_make_cluster(current))
            current = [e]
        last_mtime = e["mtime"]
        last_dir = e["source_root"]

    if current:
        clusters.append(_make_cluster(current))

    now = datetime.now().timestamp()
    for c in clusters:
        avg_age = sum((now - e["mtime"]) / 86400 for e in c["files"]) / len(c["files"])
        c["avg_age_days"] = avg_age
        c["is_active"] = avg_age <= days_active and len(c["files"]) >= 2

    return clusters


def _make_cluster(files: list) -> dict:
    names = [f["name"] for f in files]
    all_text = " ".join(names).lower()

    # Prioridade 1: keyword de projeto (cross-arquivo, mais informativo que prefix)
    kw_match = None
    for k, _, _, _ in PROJECT_KEYWORDS:
        if k in all_text:
            kw_match = k
            break

    common = longest_common_prefix(names).strip(" -_.")
    if kw_match:
        tema = kw_match
    else:
        tema = common if len(common) >= 3 else "diversos"

    cid_seed = (tema + str(int(files[0]["mtime"])) + str(len(files))).encode("utf-8")
    return {
        "id": f"cluster-{hashlib.sha1(cid_seed).hexdigest()[:8]}",
        "tema": tema,
        "tema_slug": safe_slug(tema, 30),
        "files": files,
        "is_active": False,
        "avg_age_days": 0,
    }


# ============================================================
# Lixo & Duplicatas (quarentena — NUNCA deleta)
# ============================================================

_INSTALLED_APPS_CACHE = None


def installed_apps() -> set:
    """Nomes (lowercase, sem .app) dos apps em /Applications e ~/Applications."""
    global _INSTALLED_APPS_CACHE
    if _INSTALLED_APPS_CACHE is not None:
        return _INSTALLED_APPS_CACHE
    names = set()
    for base in (Path("/Applications"), HOME / "Applications"):
        try:
            for child in base.iterdir():
                if child.suffix == ".app":
                    names.add(child.stem.lower())
        except (FileNotFoundError, PermissionError, OSError):
            continue
    _INSTALLED_APPS_CACHE = names
    return names


def detect_garbage(entry: dict, installed: set):
    """Retorna (bucket, motivo) se o item é lixo de ALTA precisão, senão None.
    NÃO deleta — quem chama só MOVE pra _REVISAR-EXCLUIR/lixo/{bucket}/.
    Conservador de propósito: na dúvida, retorna None e o item segue fluxo normal."""
    name = entry["name"]
    ext = entry["ext"]
    is_dir = entry["is_dir"]

    # 1. Download incompleto / arquivo temporário
    if ext in PARTIAL_EXTS:
        return ("downloads-incompletos", f"download incompleto/temporário ({ext})")

    # 2. Arquivo de 0 bytes
    if not is_dir and entry["size"] == 0:
        return ("vazios", "arquivo de 0 bytes")

    # 3. Pasta vazia
    if is_dir and entry["file_count"] == 0:
        return ("vazios", "pasta vazia")

    # 4. Diretório de build/deps regenerável solto no topo
    if is_dir and name.lower() in BUILD_ARTIFACT_DIRS:
        return ("build-regeneravel", f"'{name}' é regenerável (reinstala/recompila)")

    # 5. Instalador re-baixável (cruza com apps instalados pra dar contexto)
    if not is_dir and ext in INSTALLER_EXTS:
        stem = re.split(r"[ _\-.0-9]", name.lower(), 1)[0]
        match = ""
        if stem and len(stem) >= 3:
            for app in installed:
                if stem in app or (app.split() and app.split()[0] in name.lower()):
                    match = app
                    break
        if match:
            return ("instaladores", f"instalador — app '{match}' já instalado (re-baixável)")
        return ("instaladores", "instalador re-baixável (confirme se ainda precisa)")

    return None


# Assinatura (magic bytes) das extensões que têm formato binário definido.
# Só entram formatos cuja assinatura é estável no início do arquivo.
EXT_MAGIC = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".gz": (b"\x1f\x8b",),
    ".bz2": (b"BZh",),
}


def ext_lies(path: str, ext: str) -> int:
    """1 se a extensão promete um formato que o conteúdo não tem (ex.: markdown salvo
    como .pdf). 0 se bate, ou se a extensão não tem assinatura conhecida (texto)."""
    sigs = EXT_MAGIC.get(ext)
    if not sigs:
        return 0
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return 0
    return 0 if any(head.startswith(s) for s in sigs) else 1


def pick_canonical(group: list) -> dict:
    """Exemplar a MANTER: extensão honesta > nome sem cara de cópia > mais antigo
    (original) > path mais curto.

    A extensão vem primeiro porque um arquivo cuja extensão mente (ex.: `nota.md.pdf`
    que na verdade é markdown) nunca deve sobreviver a um irmão idêntico e corretamente
    nomeado, mesmo sendo mais antigo.
    """
    def rank(e):
        lies = ext_lies(e["path"], e["ext"])
        is_copy = 1 if COPY_HINT_RE.search(e["name"]) else 0
        return (lies, is_copy, e["mtime"], len(e["path"]))
    return sorted(group, key=rank)[0]


def find_duplicates(entries: list) -> dict:
    """Acha duplicatas EXATAS (arquivos por tamanho+hash completo; pastas por
    assinatura de conteúdo). Retorna {path_da_copia: (motivo, path_canonico)}.
    O canônico NÃO entra no dict — fica no lugar e é organizado normalmente.
    Nada é deletado: quem chama MOVE as cópias pra _REVISAR-EXCLUIR/duplicatas/."""
    dup_map = {}

    # --- Arquivos: agrupa por tamanho, confirma identidade por hash completo ---
    by_size = {}
    for e in entries:
        if e["is_dir"] or e["size"] == 0:
            continue
        by_size.setdefault(e["size"], []).append(e)

    for size, group in by_size.items():
        if len(group) < 2:
            continue  # tamanho único → impossível ser duplicata exata
        by_hash = {}
        for e in group:
            fh = full_file_hash(Path(e["path"]))
            if fh:
                by_hash.setdefault(fh, []).append(e)
        for ident in by_hash.values():
            if len(ident) < 2:
                continue
            canonical = pick_canonical(ident)
            for e in ident:
                if e["path"] != canonical["path"]:
                    dup_map[e["path"]] = (
                        f"duplicata exata de '{canonical['name']}' ({fmt_size(size)})",
                        canonical["path"],
                    )

    # --- Diretórios: agrupa por assinatura de conteúdo idêntica ---
    by_sig = {}
    for e in entries:
        if e["is_dir"] and e.get("dir_sig"):
            by_sig.setdefault(e["dir_sig"], []).append(e)

    for group in by_sig.values():
        if len(group) < 2:
            continue
        canonical = pick_canonical(group)
        for e in group:
            if e["path"] != canonical["path"]:
                dup_map[e["path"]] = (
                    f"pasta idêntica a '{canonical['name']}' "
                    f"({fmt_size(e['size'])}, {e['file_count']} arq)",
                    canonical["path"],
                )

    return dup_map


def _review_item(entry: dict, dest_dir: Path, reason: str, cluster: dict,
                 bucket: str, extra: dict = None) -> dict:
    """Monta item de plano destinado à quarentena (_REVISAR-EXCLUIR)."""
    item = {
        "src": entry["path"],
        "dest": str(dest_dir / entry["name"]),
        "name": entry["name"],
        "size": entry["size"],
        "is_dir": entry["is_dir"],
        "mtime": entry["mtime"],
        "age_days": entry["age_days"],
        "confidence": 0.99,  # certeza alta → move na quarentena; "revisão" = humano apagar
        "reason": reason,
        "cluster_id": cluster["id"],
        "cluster_tema": cluster["tema"],
        "is_active_cluster": False,
        "is_quickshare": False,
        "needs_review": False,
        "category_proposed": f"{REVIEW_DIR_NAME}/{bucket}",
        "review_bucket": bucket,
    }
    if extra:
        item.update(extra)
    return item


# ============================================================
# Plan
# ============================================================

def make_plan(entries: list, days_active: int, dest_root: Path,
              do_dedup: bool = True, do_trash: bool = True) -> dict:
    clusters = cluster_entries(entries, days_active)

    review_root = dest_root / REVIEW_DIR_NAME
    dup_map = find_duplicates(entries) if do_dedup else {}
    installed = installed_apps() if do_trash else set()

    items = []
    for c in clusters:
        for entry in c["files"]:
            # --- Quarentena: duplicata (prioridade máxima) ---
            if do_dedup and entry["path"] in dup_map:
                dreason, canonical = dup_map[entry["path"]]
                items.append(_review_item(
                    entry, review_root / "duplicatas", dreason, c,
                    bucket="dup", extra={"canonical": canonical}))
                continue

            # --- Quarentena: lixo ---
            gb = detect_garbage(entry, installed) if do_trash else None
            if gb:
                gbucket, greason = gb
                items.append(_review_item(
                    entry, review_root / "lixo" / gbucket, greason, c,
                    bucket="trash"))
                continue

            # --- Fluxo normal de organização ---
            cls = classify(entry)

            if c["is_active"]:
                dest_dir = ACTIVE_CLUSTER_DIR / f"_ativo-{c['tema_slug']}"
                reason = (f"trabalho ativo ({c['avg_age_days']:.0f}d, "
                          f"{len(c['files'])} arq) — cluster '{c['tema']}'")
                conf = 0.85
            elif cls["confidence"] < MID_CONF:
                dest_dir = dest_root / "_inbox" / "duvidas"
                reason = f"baixa confiança ({cls['confidence']:.2f}): {cls['reason']}"
                conf = cls["confidence"]
            else:
                dest_dir = dest_root / cls["category"]
                reason = cls["reason"]
                conf = cls["confidence"]

            dest_path = dest_dir / entry["name"]

            items.append({
                "src": entry["path"],
                "dest": str(dest_path),
                "name": entry["name"],
                "size": entry["size"],
                "is_dir": entry["is_dir"],
                "mtime": entry["mtime"],
                "age_days": entry["age_days"],
                "confidence": conf,
                "reason": reason,
                "cluster_id": c["id"],
                "cluster_tema": c["tema"],
                "is_active_cluster": c["is_active"],
                "is_quickshare": cls["is_quickshare"],
                "needs_review": conf < MID_CONF,
                "category_proposed": cls["category"],
                "review_bucket": None,
            })

    # H/M/L contam só itens de organização; lixo/dups são categoria à parte.
    org_items = [i for i in items if not i.get("review_bucket")]
    review_items = [i for i in items if i.get("review_bucket")]
    stats = {
        "total": len(items),
        "high": sum(1 for i in org_items if i["confidence"] >= HIGH_CONF),
        "mid": sum(1 for i in org_items if MID_CONF <= i["confidence"] < HIGH_CONF),
        "low": sum(1 for i in org_items if i["confidence"] < MID_CONF),
        "active_clusters": sum(1 for c in clusters if c["is_active"]),
        "total_clusters": len(clusters),
        "dups": sum(1 for i in review_items if i["review_bucket"] == "dup"),
        "trash": sum(1 for i in review_items if i["review_bucket"] == "trash"),
        "review_reclaim_bytes": sum(i["size"] for i in review_items),
    }

    return {
        "ts": now_ts(),
        "days_active": days_active,
        "dest_root": str(dest_root),
        "review_root": str(review_root),
        "items": items,
        "stats": stats,
    }


# ============================================================
# Apply
# ============================================================

def apply_plan(plan: dict, min_confidence: float = MID_CONF, auto: bool = False) -> dict:
    moves = []

    for item in plan["items"]:
        if item["confidence"] < min_confidence and not auto:
            moves.append({
                "src": item["src"], "dest": item["dest"],
                "status": "skipped",
                "note": f"confiança {item['confidence']:.2f} < limiar {min_confidence:.2f}",
                "applied_at": None,
            })
            continue

        src = Path(item["src"])
        dest = Path(item["dest"])

        if not src.exists():
            moves.append({
                "src": str(src), "dest": str(dest),
                "status": "skipped", "note": "origem não existe (já movida?)",
                "applied_at": None,
            })
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            moves.append({
                "src": str(src), "dest": str(dest),
                "status": "failed", "note": f"falha ao criar diretório: {e}",
                "applied_at": None,
            })
            continue

        final_dest = dest
        if final_dest.exists():
            if final_dest.is_file() and src.is_file():
                src_h = file_hash(src)
                dest_h = file_hash(final_dest)
                if src_h and src_h == dest_h:
                    moves.append({
                        "src": str(src), "dest": str(final_dest),
                        "status": "skipped", "note": "duplicata exata já no destino",
                        "applied_at": None,
                    })
                    continue
            stem = final_dest.stem
            suffix = final_dest.suffix
            ts_label = datetime.fromtimestamp(item["mtime"]).strftime("%Y%m%d-%H%M%S")
            final_dest = final_dest.parent / f"{stem}--{ts_label}{suffix}"
            counter = 1
            while final_dest.exists():
                final_dest = final_dest.parent / f"{stem}--{ts_label}-{counter}{suffix}"
                counter += 1

        try:
            shutil.move(str(src), str(final_dest))
            moves.append({
                "src": str(src), "dest": str(final_dest),
                "status": "moved" if str(final_dest) == str(dest) else "renamed",
                "note": item["reason"],
                "applied_at": datetime.now().timestamp(),
                "confidence": item["confidence"],
                "is_active_cluster": item["is_active_cluster"],
                "cluster_tema": item.get("cluster_tema", ""),
                "size": item.get("size", 0),
                "review_bucket": item.get("review_bucket"),
            })
        except Exception as e:
            moves.append({
                "src": str(src), "dest": str(dest),
                "status": "failed", "note": f"erro ao mover: {e}",
                "applied_at": None,
            })

    return {
        "ts": now_ts(),
        "plan_ts": plan["ts"],
        "moves": moves,
        "stats": {
            "moved": sum(1 for m in moves if m["status"] == "moved"),
            "renamed": sum(1 for m in moves if m["status"] == "renamed"),
            "skipped": sum(1 for m in moves if m["status"] == "skipped"),
            "failed": sum(1 for m in moves if m["status"] == "failed"),
        }
    }


# ============================================================
# Activity index
# ============================================================

def update_activity_index(manifest: dict, manifest_path: str):
    idx_path = RUNTIME_DIR / "activity-index.json"
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text())
        except Exception:
            idx = {"entries": {}}
    else:
        idx = {"entries": {}}

    for m in manifest["moves"]:
        if m["status"] in ("moved", "renamed"):
            entries = idx["entries"].setdefault(m["src"], [])
            entries.append({
                "current": m["dest"],
                "moved_at": m["applied_at"],
                "manifest": manifest_path,
                "reason": m.get("note", ""),
            })

    idx_path.write_text(json.dumps(idx, indent=2, ensure_ascii=False))


def lookup_path(query: str) -> list:
    idx_path = RUNTIME_DIR / "activity-index.json"
    if not idx_path.exists():
        return []
    try:
        idx = json.loads(idx_path.read_text())
    except Exception:
        return []
    results = []
    q = query.lower()
    for orig, history in idx.get("entries", {}).items():
        if q in orig.lower() or q in Path(orig).name.lower():
            latest = history[-1]
            results.append({
                "original": orig,
                "current": latest["current"],
                "moved_at": latest["moved_at"],
            })
    return results


# ============================================================
# Undo
# ============================================================

def undo_manifest(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    reverts = []
    for m in reversed(manifest["moves"]):
        if m["status"] not in ("moved", "renamed"):
            continue
        src = Path(m["dest"])
        dest = Path(m["src"])
        if not src.exists():
            reverts.append({
                "src": str(src), "dest": str(dest),
                "status": "skipped", "note": "destino atual não existe",
            })
            continue
        if dest.exists():
            reverts.append({
                "src": str(src), "dest": str(dest),
                "status": "skipped", "note": "origem original já existe (colisão no undo)",
            })
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            reverts.append({"src": str(src), "dest": str(dest), "status": "reverted"})
        except Exception as e:
            reverts.append({
                "src": str(src), "dest": str(dest),
                "status": "failed", "note": str(e),
            })

    return {
        "ts": now_ts(),
        "reverted_manifest": str(manifest_path),
        "reverts": reverts,
        "stats": {
            "reverted": sum(1 for r in reverts if r["status"] == "reverted"),
            "skipped": sum(1 for r in reverts if r["status"] == "skipped"),
            "failed": sum(1 for r in reverts if r["status"] == "failed"),
        }
    }


# ============================================================
# Reports
# ============================================================

def render_plan_report(plan: dict, out_path: Path):
    lines = [
        f"# Plano de organização — {plan['ts']}",
        "",
        f"**Modo**: dry-run (nada foi movido ainda)  ",
        f"**Janela ativo**: {plan['days_active']} dias  ",
        f"**Destino raiz**: `{plan['dest_root']}`",
        "",
        "## Sumário",
        "",
        f"- Total: **{plan['stats']['total']}** arquivos/pastas",
        f"- HIGH (≥{HIGH_CONF}): **{plan['stats']['high']}** — aplicar direto",
        f"- MID ({MID_CONF}–{HIGH_CONF}): **{plan['stats']['mid']}** — aplicar c/ revisão",
        f"- LOW (<{MID_CONF}): **{plan['stats']['low']}** — vai pra `_inbox/duvidas/`",
        f"- Clusters ativos: **{plan['stats']['active_clusters']}** / {plan['stats']['total_clusters']}",
        f"- 🗑 Duplicatas + lixo: **{plan['stats'].get('dups', 0) + plan['stats'].get('trash', 0)}** "
        f"({fmt_size(plan['stats'].get('review_reclaim_bytes', 0))}) → `{REVIEW_DIR_NAME}/` (você exclui manual)",
        "",
        "## Como aplicar",
        "",
        "```bash",
        "# Aplica HIGH+MID, LOW vai pra _inbox automaticamente",
        f"python3 {SELF} apply --auto",
        "",
        "# Ou só HIGH (mais conservador)",
        f"python3 {SELF} apply --min-confidence {HIGH_CONF}",
        "",
        "# Reverter última run a qualquer momento",
        f"python3 {SELF} undo",
        "```",
        "",
    ]

    # Ativos: agrupa por destino real (tema_slug) — clusters distintos com mesmo
    # tema fundem no destino, então fundem no relatório também.
    active_by_slug = {}
    inactive_items = []
    review_items = []
    for item in plan["items"]:
        if item.get("review_bucket"):
            review_items.append(item)
        elif item["is_active_cluster"]:
            slug = safe_slug(item["cluster_tema"])
            active_by_slug.setdefault(slug, {"tema": item["cluster_tema"], "items": []})["items"].append(item)
        else:
            inactive_items.append(item)

    # Seção de quarentena (vem primeiro: é o que o humano vai conferir e apagar).
    if review_items:
        review_root = plan.get("review_root", f"~/Documents/Organizado/{REVIEW_DIR_NAME}")
        reclaim = sum(i["size"] for i in review_items)
        lines.extend([
            "## \U0001F5D1 Pra revisar e EXCLUIR manualmente",
            "",
            f"Vão pra `{review_root}/`. **A skill não apaga** — depois de conferir, "
            f"você deleta a pasta. Recuperável até lá (`undo`). Total: **{fmt_size(reclaim)}**.",
            "",
        ])
        dups = [i for i in review_items if i["review_bucket"] == "dup"]
        trash = [i for i in review_items if i["review_bucket"] == "trash"]
        if dups:
            lines.append(f"### ♊ Duplicatas exatas → `{REVIEW_DIR_NAME}/duplicatas/` ({len(dups)})")
            lines.append("")
            lines.append("O original fica no lugar; só a cópia é movida.")
            lines.append("")
            for i in sorted(dups, key=lambda x: -x["size"]):
                emoji = "\U0001F4C1" if i["is_dir"] else "\U0001F4C4"
                canon = i.get("canonical", "")
                canon_name = Path(canon).name if canon else "?"
                lines.append(f"- {emoji} `{i['name']}` ({fmt_size(i['size'])}) — mantém `{canon_name}`")
            lines.append("")
        if trash:
            by_bucket = {}
            for i in trash:
                b = Path(i["dest"]).parent.name  # vazios / instaladores / downloads-incompletos / ...
                by_bucket.setdefault(b, []).append(i)
            for b in sorted(by_bucket.keys()):
                grp = by_bucket[b]
                tot = sum(x["size"] for x in grp)
                lines.append(f"### \U0001F5D1 Lixo: {b} → `{REVIEW_DIR_NAME}/lixo/{b}/` ({len(grp)}, {fmt_size(tot)})")
                lines.append("")
                for i in sorted(grp, key=lambda x: -x["size"]):
                    emoji = "\U0001F4C1" if i["is_dir"] else "\U0001F4C4"
                    lines.append(f"- {emoji} `{i['name']}` ({fmt_size(i['size'])}, {i['age_days']:.0f}d) — {i['reason']}")
                lines.append("")

    if active_by_slug:
        lines.extend([
            "## \U0001F525 Clusters de trabalho ativo",
            "",
            "Vão pro Desktop em pasta `_ativo-{tema}/` pra não quebrar fluxo.",
            "",
        ])
        for slug in sorted(active_by_slug.keys()):
            grp = active_by_slug[slug]
            items = sorted(grp["items"], key=lambda x: -x["mtime"])
            lines.append(f"### `~/Desktop/_ativo-{slug}/` ({len(items)} arq)")
            lines.append("")
            for i in items:
                emoji = "\U0001F4C1" if i["is_dir"] else "\U0001F4C4"
                lines.append(
                    f"- {emoji} `{i['name']}` ({fmt_size(i['size'])}, {i['age_days']:.0f}d)"
                )
            lines.append("")

    if inactive_items:
        by_cat = {}
        for i in inactive_items:
            by_cat.setdefault(i["category_proposed"], []).append(i)

        lines.extend([
            "## \U0001F4C2 Arquivamento",
            "",
            "Sem trabalho ativo recente, organizados por categoria.",
            "",
        ])
        for cat in sorted(by_cat.keys()):
            items = by_cat[cat]
            lines.append(f"### `{cat}/` ({len(items)} arq)")
            lines.append("")
            for i in sorted(items, key=lambda x: -x["confidence"]):
                emoji = "\U0001F4C1" if i["is_dir"] else "\U0001F4C4"
                if i["confidence"] >= HIGH_CONF:
                    tag = "[HIGH]"
                elif i["confidence"] >= MID_CONF:
                    tag = "[MID]"
                else:
                    tag = "[LOW ⚠️]"
                lines.append(
                    f"- {tag} {emoji} `{i['name']}` "
                    f"({fmt_size(i['size'])}, {i['age_days']:.0f}d) — "
                    f"conf {i['confidence']:.2f} — {i['reason']}"
                )
                lines.append(f"   → `{i['dest']}`")
            lines.append("")

    out_path.write_text("\n".join(lines))


def render_apply_report(manifest: dict, plan: dict, out_path: Path):
    review_moves = [m for m in manifest["moves"]
                    if m["status"] in ("moved", "renamed") and m.get("review_bucket")]
    review_reclaim = sum(m.get("size", 0) for m in review_moves)
    review_root = plan.get("review_root", str(Path(DEFAULT_DEST_ROOT) / REVIEW_DIR_NAME))

    lines = [
        f"# Relatório de organização — {manifest['ts']}",
        "",
        f"**Plano executado**: {manifest['plan_ts']}",
        "",
        "## Resultado",
        "",
        f"- ✅ Movidos: **{manifest['stats']['moved']}**",
        f"- \U0001F504 Renomeados (colisão): **{manifest['stats']['renamed']}**",
        f"- ⏭️ Pulados: **{manifest['stats']['skipped']}**",
        f"- ❌ Falhados: **{manifest['stats']['failed']}**",
        "",
    ]

    if review_moves:
        lines.extend([
            "## \U0001F5D1 Pra você EXCLUIR manualmente",
            "",
            f"Movi **{len(review_moves)}** itens de lixo/duplicata (**{fmt_size(review_reclaim)}**) pra:",
            "",
            f"```\n{review_root}\n```",
            "",
            "Confira e **apague essa pasta** quando quiser recuperar o espaço. "
            "A skill não deletou nada — se errei em algo, `undo` traz de volta.",
            "",
        ])

    lines += [
        "## Onde está cada coisa agora",
        "",
        "Agrupado por pasta destino. Use `Cmd+Click` no path pra abrir no Finder.",
        "",
    ]

    moved = [m for m in manifest["moves"] if m["status"] in ("moved", "renamed")]

    by_dest_dir = {}
    for m in moved:
        d = str(Path(m["dest"]).parent)
        by_dest_dir.setdefault(d, []).append(m)

    for d in sorted(by_dest_dir.keys()):
        items = by_dest_dir[d]
        lines.append(f"### `{d}/`")
        lines.append("")
        for m in items:
            orig_name = Path(m["src"]).name
            new_name = Path(m["dest"]).name
            renamed_mark = "" if orig_name == new_name else f" (renomeado de `{orig_name}`)"
            note = m.get("note", "")
            lines.append(f"- `{new_name}`{renamed_mark} — _{note}_")
        lines.append("")

    skipped = [m for m in manifest["moves"] if m["status"] == "skipped"]
    if skipped:
        lines.extend(["## Pulados", ""])
        for m in skipped:
            lines.append(f"- `{m['src']}` — _{m['note']}_")
        lines.append("")

    failed = [m for m in manifest["moves"] if m["status"] == "failed"]
    if failed:
        lines.extend(["## ⚠️ Falhas", ""])
        for m in failed:
            lines.append(f"- `{m['src']}` → `{m['dest']}` — _{m['note']}_")
        lines.append("")

    lines.extend([
        "## Reversão",
        "",
        "Se algo foi parar no lugar errado, reverte tudo desta run:",
        "",
        "```bash",
        f"python3 {SELF} undo",
        "```",
        "",
        "Ou consulta um arquivo específico:",
        "",
        "```bash",
        f'python3 {SELF} where "nome-do-arquivo"',
        "```",
        "",
    ])

    out_path.write_text("\n".join(lines))


# ============================================================
# CLI handlers
# ============================================================

def cmd_scan(args):
    ensure_runtime()
    sources = [Path(s).expanduser() for s in (args.source or [])] or DEFAULT_SOURCES
    entries = scan_sources(sources)
    out = RUNTIME_DIR / f"scan-{now_ts()}.json"
    out.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    print(f"Scan: {len(entries)} entradas")
    print(f"Saída: {out}")
    print("---JSON---")
    print(json.dumps({"scan_path": str(out), "count": len(entries)}))


def cmd_plan(args):
    ensure_runtime()
    if getattr(args, "scan_file", None):
        entries = json.loads(Path(args.scan_file).read_text())
    else:
        sources = [Path(s).expanduser() for s in (args.source or [])] or DEFAULT_SOURCES
        entries = scan_sources(sources)

    dest_root = Path(args.dest).expanduser() if args.dest else DEFAULT_DEST_ROOT
    do_dedup = not getattr(args, "no_dedup", False)
    do_trash = not getattr(args, "no_trash", False)
    plan = make_plan(entries, args.days, dest_root, do_dedup=do_dedup, do_trash=do_trash)

    plan_path = RUNTIME_DIR / f"plan-{plan['ts']}.json"
    plan["plan_path"] = str(plan_path)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))

    report_path = REPORT_DIR / f"_organize-plan-{plan['ts']}.md"
    render_plan_report(plan, report_path)

    s = plan["stats"]
    print(f"Plano: {s['total']} itens ({s['high']}H / {s['mid']}M / {s['low']}L)")
    print(f"  - clusters ativos: {s['active_clusters']}/{s['total_clusters']}")
    print(f"  - quarentena: {s.get('dups', 0)} dups + {s.get('trash', 0)} lixo "
          f"({fmt_size(s.get('review_reclaim_bytes', 0))}) → {REVIEW_DIR_NAME}/")
    print(f"Plan JSON: {plan_path}")
    print(f"Relatório: {report_path}")
    print("---JSON---")
    print(json.dumps({
        "plan_path": str(plan_path),
        "report_path": str(report_path),
        "review_root": plan.get("review_root"),
        "stats": s,
    }))


def cmd_apply(args):
    ensure_runtime()
    plan_arg = getattr(args, "plan", None) or "latest"
    if plan_arg == "latest":
        plans = sorted(RUNTIME_DIR.glob("plan-*.json"))
        if not plans:
            print("ERRO: nenhum plano encontrado. Rode 'plan' primeiro.")
            sys.exit(1)
        plan_path = plans[-1]
    else:
        plan_path = Path(plan_arg)
        if not plan_path.is_absolute() and not plan_path.exists():
            cand = RUNTIME_DIR / plan_path
            if cand.exists():
                plan_path = cand

    plan = json.loads(plan_path.read_text())

    if args.min_confidence is not None:
        min_conf = args.min_confidence
    elif args.auto:
        min_conf = 0.0
    else:
        min_conf = MID_CONF

    manifest = apply_plan(plan, min_confidence=min_conf, auto=args.auto)

    manifest_path = RUNTIME_DIR / f"manifest-{manifest['ts']}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    update_activity_index(manifest, str(manifest_path))

    report_path = REPORT_DIR / f"_organize-report-{manifest['ts']}.md"
    render_apply_report(manifest, plan, report_path)

    s = manifest["stats"]
    review_moves = [m for m in manifest["moves"]
                    if m["status"] in ("moved", "renamed") and m.get("review_bucket")]
    review_reclaim = sum(m.get("size", 0) for m in review_moves)
    review_root = plan.get("review_root", str(DEFAULT_DEST_ROOT / REVIEW_DIR_NAME))
    print(f"Apply: {s['moved']} movidos / {s['renamed']} renomeados / "
          f"{s['skipped']} pulados / {s['failed']} falhados")
    if review_moves:
        print(f"  - quarentena: {len(review_moves)} itens ({fmt_size(review_reclaim)}) "
              f"em {review_root} — EXCLUA MANUALMENTE")
    print(f"Manifest: {manifest_path}")
    print(f"Relatório: {report_path}")
    print("---JSON---")
    print(json.dumps({
        "manifest_path": str(manifest_path),
        "report_path": str(report_path),
        "review_root": review_root,
        "review_reclaim_bytes": review_reclaim,
        "stats": s,
    }))


def cmd_undo(args):
    ensure_runtime()
    m_arg = getattr(args, "manifest", None) or "latest"
    if m_arg == "latest":
        manifests = sorted(RUNTIME_DIR.glob("manifest-*.json"))
        if not manifests:
            print("ERRO: nenhum manifest pra reverter.")
            sys.exit(1)
        m_path = manifests[-1]
    else:
        m_path = Path(m_arg)
        if not m_path.is_absolute() and not m_path.exists():
            cand = RUNTIME_DIR / m_path
            if cand.exists():
                m_path = cand

    result = undo_manifest(m_path)
    out = RUNTIME_DIR / f"undo-{result['ts']}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    s = result["stats"]
    print(f"Undo: {s['reverted']} revertidos / {s['skipped']} pulados / "
          f"{s['failed']} falhados")
    print(f"Log: {out}")
    print("---JSON---")
    print(json.dumps({"undo_log": str(out), "stats": s}))


def cmd_where(args):
    results = lookup_path(args.query)
    if not results:
        print(f"Nenhuma entrada no índice pra '{args.query}'.")
        return
    for r in results:
        moved_at = (datetime.fromtimestamp(r["moved_at"]).strftime("%Y-%m-%d %H:%M")
                    if r["moved_at"] else "?")
        print(f"  {r['original']}")
        print(f"  → {r['current']} (em {moved_at})")
        print()


def cmd_status(args):
    ensure_runtime()
    plans = sorted(RUNTIME_DIR.glob("plan-*.json"))
    manifests = sorted(RUNTIME_DIR.glob("manifest-*.json"))
    print(f"Runtime: {RUNTIME_DIR}")
    print(f"Planos: {len(plans)}")
    if plans:
        print(f"  Último: {plans[-1].name}")
    print(f"Manifests: {len(manifests)}")
    if manifests:
        try:
            last = json.loads(manifests[-1].read_text())
            print(f"  Último: {manifests[-1].name}")
            print(f"  Stats: {last['stats']}")
        except Exception:
            pass
    idx_path = RUNTIME_DIR / "activity-index.json"
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text())
            print(f"Activity index: {len(idx.get('entries', {}))} arquivos rastreados")
        except Exception:
            pass


def cmd_dryrun(args):
    plan_args = argparse.Namespace(
        scan_file=None,
        source=getattr(args, "source", None),
        days=getattr(args, "days", DEFAULT_DAYS_ACTIVE),
        dest=getattr(args, "dest", None),
        no_dedup=getattr(args, "no_dedup", False),
        no_trash=getattr(args, "no_trash", False),
    )
    cmd_plan(plan_args)


def cmd_auto(args):
    plan_args = argparse.Namespace(
        scan_file=None,
        source=getattr(args, "source", None),
        days=getattr(args, "days", DEFAULT_DAYS_ACTIVE),
        dest=getattr(args, "dest", None),
        no_dedup=getattr(args, "no_dedup", False),
        no_trash=getattr(args, "no_trash", False),
    )
    cmd_plan(plan_args)
    plans = sorted(RUNTIME_DIR.glob("plan-*.json"))
    apply_args = argparse.Namespace(
        plan=str(plans[-1]),
        auto=True,
        min_confidence=None,
    )
    cmd_apply(apply_args)


def main():
    parser = argparse.ArgumentParser(
        description="Organiza arquivos sem deletar (skill organizar-maquina)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Escaneia origens e classifica")
    p_scan.add_argument("--source", action="append")
    p_scan.set_defaults(func=cmd_scan)

    p_plan = sub.add_parser("plan", help="Gera plano (dry-run)")
    p_plan.add_argument("--scan-file")
    p_plan.add_argument("--source", action="append")
    p_plan.add_argument("--days", type=int, default=DEFAULT_DAYS_ACTIVE)
    p_plan.add_argument("--dest")
    p_plan.add_argument("--no-dedup", action="store_true",
                        help="Não detectar duplicatas")
    p_plan.add_argument("--no-trash", action="store_true",
                        help="Não detectar lixo (instaladores, vazios, etc.)")
    p_plan.set_defaults(func=cmd_plan)

    p_apply = sub.add_parser("apply", help="Aplica plano")
    p_apply.add_argument("--plan", default="latest")
    p_apply.add_argument("--auto", action="store_true",
                         help="Move TUDO (LOW vai pra _inbox)")
    p_apply.add_argument("--min-confidence", type=float)
    p_apply.set_defaults(func=cmd_apply)

    p_undo = sub.add_parser("undo", help="Reverte última run")
    p_undo.add_argument("--manifest", default="latest")
    p_undo.set_defaults(func=cmd_undo)

    p_where = sub.add_parser("where", help="Onde está agora um arquivo")
    p_where.add_argument("query")
    p_where.set_defaults(func=cmd_where)

    p_status = sub.add_parser("status", help="Status das runs")
    p_status.set_defaults(func=cmd_status)

    p_dry = sub.add_parser("dryrun", help="scan + plan")
    p_dry.add_argument("--source", action="append")
    p_dry.add_argument("--days", type=int, default=DEFAULT_DAYS_ACTIVE)
    p_dry.add_argument("--dest")
    p_dry.add_argument("--no-dedup", action="store_true")
    p_dry.add_argument("--no-trash", action="store_true")
    p_dry.set_defaults(func=cmd_dryrun)

    p_auto = sub.add_parser("auto", help="scan + plan + apply --auto")
    p_auto.add_argument("--source", action="append")
    p_auto.add_argument("--days", type=int, default=DEFAULT_DAYS_ACTIVE)
    p_auto.add_argument("--dest")
    p_auto.add_argument("--no-dedup", action="store_true")
    p_auto.add_argument("--no-trash", action="store_true")
    p_auto.set_defaults(func=cmd_auto)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
