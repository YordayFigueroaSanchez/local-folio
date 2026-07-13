"""Tests de db._migrate_legacy_data_dir() usando directorios temporales.

Estos tests nunca tocan PROJECT_ROOT/scripts/data reales: la funcion se
llama directamente con legacy_dir/data_dir apuntando a tempfile.
TemporaryDirectory(), aislados por completo del proyecto real.
"""

import os
import tempfile
import unittest

from local_folio import db


class MigrateLegacyDataDirTests(unittest.TestCase):
    def setUp(self) -> None:
        self._legacy_tmp = tempfile.TemporaryDirectory()
        self._data_tmp = tempfile.TemporaryDirectory()
        self.legacy_dir = self._legacy_tmp.name
        self.data_dir = os.path.join(self._data_tmp.name, "data")

    def tearDown(self) -> None:
        self._legacy_tmp.cleanup()
        self._data_tmp.cleanup()

    def _migrate(self) -> list[str]:
        return db._migrate_legacy_data_dir(
            legacy_dir=self.legacy_dir,
            data_dir=self.data_dir,
            db_filename="mi_portafolio.db",
        )

    def test_fresh_install_is_a_noop(self) -> None:
        result = self._migrate()
        self.assertEqual(result, [])
        self.assertFalse(os.path.isdir(self.data_dir), "no debe crear data_dir si no hay nada que migrar")

    def test_migrates_db_file(self) -> None:
        db_path = os.path.join(self.legacy_dir, "mi_portafolio.db")
        with open(db_path, "w", encoding="utf-8") as f:
            f.write("contenido db")

        result = self._migrate()

        self.assertIn("mi_portafolio.db", result)
        self.assertFalse(os.path.exists(db_path))
        new_path = os.path.join(self.data_dir, "mi_portafolio.db")
        self.assertTrue(os.path.isfile(new_path))
        with open(new_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "contenido db")

    def test_migrates_active_db_config(self) -> None:
        with open(os.path.join(self.legacy_dir, "active_db.txt"), "w", encoding="utf-8") as f:
            f.write("mi_portafolio.db")

        result = self._migrate()

        self.assertIn("active_db.txt", result)
        self.assertFalse(os.path.exists(os.path.join(self.legacy_dir, "active_db.txt")))
        self.assertTrue(os.path.isfile(os.path.join(self.data_dir, "active_db.txt")))

    def test_migrates_backups_dir_and_removes_legacy_if_empty(self) -> None:
        backups_dir = os.path.join(self.legacy_dir, "backups")
        os.makedirs(backups_dir)
        for i in range(3):
            with open(os.path.join(backups_dir, f"backup_{i}.db"), "w", encoding="utf-8") as f:
                f.write(f"backup {i}")

        result = self._migrate()

        self.assertTrue(any("backups/" in item for item in result))
        new_backups = os.path.join(self.data_dir, "backups")
        self.assertEqual(
            sorted(os.listdir(new_backups)),
            ["backup_0.db", "backup_1.db", "backup_2.db"],
        )
        self.assertFalse(os.path.isdir(backups_dir), "el directorio legacy vacio debe eliminarse")

    def test_merges_backups_without_clobbering_existing_files(self) -> None:
        legacy_backups = os.path.join(self.legacy_dir, "backups")
        os.makedirs(legacy_backups)
        with open(os.path.join(legacy_backups, "shared.db"), "w", encoding="utf-8") as f:
            f.write("legacy version")
        with open(os.path.join(legacy_backups, "only_legacy.db"), "w", encoding="utf-8") as f:
            f.write("only in legacy")

        new_backups = os.path.join(self.data_dir, "backups")
        os.makedirs(new_backups)
        with open(os.path.join(new_backups, "shared.db"), "w", encoding="utf-8") as f:
            f.write("data_dir version (no debe pisarse)")

        self._migrate()

        with open(os.path.join(new_backups, "shared.db"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "data_dir version (no debe pisarse)")
        self.assertTrue(os.path.isfile(os.path.join(new_backups, "only_legacy.db")))
        # El archivo en conflicto se deja intacto en la ubicacion legacy
        # (nunca se pierde, aunque no se pudo mover sin pisar el existente).
        self.assertTrue(os.path.isfile(os.path.join(legacy_backups, "shared.db")))
        self.assertFalse(os.path.isfile(os.path.join(legacy_backups, "only_legacy.db")))

    def test_does_not_overwrite_existing_destination_db(self) -> None:
        with open(os.path.join(self.legacy_dir, "mi_portafolio.db"), "w", encoding="utf-8") as f:
            f.write("legacy content")

        os.makedirs(self.data_dir)
        new_db_path = os.path.join(self.data_dir, "mi_portafolio.db")
        with open(new_db_path, "w", encoding="utf-8") as f:
            f.write("data_dir content (no debe pisarse)")

        result = self._migrate()

        self.assertNotIn("mi_portafolio.db", result)
        with open(new_db_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "data_dir content (no debe pisarse)")
        # El archivo legacy tampoco se pierde: queda donde estaba.
        self.assertTrue(os.path.isfile(os.path.join(self.legacy_dir, "mi_portafolio.db")))

    def test_second_run_is_idempotent(self) -> None:
        with open(os.path.join(self.legacy_dir, "mi_portafolio.db"), "w", encoding="utf-8") as f:
            f.write("contenido")

        first = self._migrate()
        second = self._migrate()

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])


if __name__ == "__main__":
    unittest.main()
