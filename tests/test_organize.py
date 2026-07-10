"""Testes do engine organize.py — cobrem os fixes de proteção de dados.

Rodar da raiz do repo:
    python3 -m unittest discover tests -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "skills" / "organizar-maquina" / "scripts"))

import organize  # noqa: E402


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="organize-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestSymlinkFicaForaDoPlano(TempDirTest):
    """Symlink no Desktop não pode virar move do ALVO: o plano arrancaria
    um projeto inteiro do lugar e deixaria o link quebrado."""

    def test_scan_pula_symlink(self):
        desktop = self.tmp / "Desktop"
        alvo = self.tmp / "projeto-real"
        (alvo / "src").mkdir(parents=True)
        (alvo / "src" / "main.py").write_text("print('oi')\n")
        desktop.mkdir()
        (desktop / "meu-link").symlink_to(alvo)
        (desktop / "solto.txt").write_text("arquivo normal\n")

        entries = organize.scan_sources([desktop])

        paths = [e["path"] for e in entries]
        self.assertEqual(len(entries), 1)
        self.assertNotIn(str(alvo), paths)          # alvo não entra
        self.assertTrue(all("meu-link" not in p for p in paths))  # link não entra
        self.assertIn(str((desktop / "solto.txt").resolve()), paths)

    def test_scan_pula_symlink_quebrado(self):
        desktop = self.tmp / "Desktop"
        desktop.mkdir()
        (desktop / "link-quebrado").symlink_to(self.tmp / "nao-existe")

        entries = organize.scan_sources([desktop])
        self.assertEqual(entries, [])


class TestColisaoUsaHashCompleto(TempDirTest):
    """Colisão de nome no destino só é 'duplicata exata' com tamanho igual e
    sha256 do arquivo INTEIRO igual. Mesmo começo + fim diferente = renomeia."""

    def _plan_para(self, src: Path, dest: Path) -> dict:
        return {
            "ts": "teste", "items": [{
                "src": str(src), "dest": str(dest), "name": src.name,
                "size": src.stat().st_size, "is_dir": False,
                "mtime": src.stat().st_mtime, "age_days": 0.0,
                "confidence": 0.9, "reason": "teste",
                "cluster_id": "c", "cluster_tema": "t",
                "is_active_cluster": False, "is_quickshare": False,
                "needs_review": False, "category_proposed": "x",
                "review_bucket": None,
            }],
        }

    def test_mesmo_comeco_fim_diferente_renomeia(self):
        head = b"A" * 70000  # maior que os 64KB do hash de classificação
        src = self.tmp / "relatorio.pdf"
        dest_dir = self.tmp / "destino"
        dest_dir.mkdir()
        dest = dest_dir / "relatorio.pdf"
        src.write_bytes(head + b"CONTEUDO-NOVO")
        dest.write_bytes(head + b"conteudo-velho")

        manifest = organize.apply_plan(self._plan_para(src, dest), auto=True)

        self.assertEqual(manifest["stats"]["renamed"], 1)
        self.assertEqual(manifest["stats"]["skipped"], 0)
        self.assertFalse(src.exists())               # origem foi movida
        self.assertTrue(dest.exists())               # destino antigo intacto
        self.assertEqual(dest.read_bytes()[-14:], b"conteudo-velho")

    def test_identico_byte_a_byte_pula(self):
        conteudo = b"B" * 70000 + b"igual"
        src = self.tmp / "doc.pdf"
        dest_dir = self.tmp / "destino"
        dest_dir.mkdir()
        dest = dest_dir / "doc.pdf"
        src.write_bytes(conteudo)
        dest.write_bytes(conteudo)

        manifest = organize.apply_plan(self._plan_para(src, dest), auto=True)

        self.assertEqual(manifest["stats"]["skipped"], 1)
        self.assertEqual(manifest["stats"]["moved"], 0)
        self.assertTrue(src.exists())                # nada saiu do lugar


class TestSegredosFicamOndeEstao(TempDirTest):
    """Credencial nunca entra no plano de moves: destino fica em ~/Documents,
    que sincroniza com iCloud (defeito #5 da run real de 2026-06-14)."""

    def _entry(self, path: Path) -> dict:
        e = organize.scan_path(path)
        assert e is not None
        return e

    def test_detecta_por_nome(self):
        for nome in (".env", ".env.local", "id_rsa", "id_ed25519",
                     ".netrc", "credentials.json", "cert.pem",
                     "backup.p12", "infra.tfstate"):
            p = self.tmp / nome
            p.write_text("x")
            self.assertIsNotNone(organize.detect_secret(self._entry(p)), nome)

    def test_detecta_chave_pem_com_nome_atipico(self):
        p = self.tmp / "servidor-antigo"
        p.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n"
                     "-----END OPENSSH PRIVATE KEY-----\n")
        self.assertIsNotNone(organize.detect_secret(self._entry(p)))

    def test_nao_marca_arquivo_comum(self):
        for nome in ("relatorio.pdf", "apresentacao.key", "id_rsa.pub",
                     "notas.txt", "config.json"):
            p = self.tmp / nome
            p.write_text("conteudo comum")
            self.assertIsNone(organize.detect_secret(self._entry(p)), nome)

    def test_make_plan_retem_segredo_fora_dos_moves(self):
        desktop = self.tmp / "Desktop"
        desktop.mkdir()
        (desktop / ".env").write_text("API_KEY=abc123\n")
        (desktop / "relatorio.pdf").write_bytes(b"%PDF-conteudo")

        entries = organize.scan_sources([desktop])
        plan = organize.make_plan(entries, days_active=0,
                                  dest_root=self.tmp / "Organizado")

        nomes_movidos = [i["name"] for i in plan["items"]]
        self.assertNotIn(".env", nomes_movidos)
        self.assertIn("relatorio.pdf", nomes_movidos)
        self.assertEqual(plan["stats"]["secrets"], 1)
        self.assertEqual(plan["secrets"][0]["name"], ".env")


if __name__ == "__main__":
    unittest.main()
