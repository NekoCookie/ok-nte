import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.char.core.CharFactory import get_char_implementation_class
from src.char.core.CharRegistry import CharRegistry, char_registry
from src.char.custom.CustomCharDb import DB_SCHEMA_VERSION, CustomCharDb
from src.char.custom.CustomCharDbMigrator import MigrationContext
from src.char.Requiem import Requiem
from src.char.Zero import Zero
from src.lw.zankou_main_dps import ZankouMainDps


class TestCharImplDb(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "db.json")
        self.features_dir = os.path.join(self.temp_dir, "features")
        os.makedirs(self.features_dir)
        CustomCharDb.reset_instance()
        self.context = MigrationContext(
            is_builtin_impl=lambda impl_id: str(impl_id).startswith("builtin:"),
            get_builtin_prefix=lambda: "[built-in] ",
            iter_builtin_impl_items=lambda: [("Zero", "builtin:zero")],
            generate_combo_id=lambda _existing: "combo_generated",
        )

    def tearDown(self):
        CustomCharDb.reset_instance()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pre_v7_records_migrate_all_lw_impl_ids(self):
        legacy = {
            "schema_version": 5,
            "combos": {"combo_text": {"name": "Text", "content": "skill"}},
            "characters": {
                "char_builtin": {"name": "Zero", "combo_id": "char_zero", "feature_ids": []},
                "char_custom": {"name": "Custom", "combo_id": "combo_text", "feature_ids": []},
                "char_requiem": {
                    "name": "Requiem",
                    "combo_id": "char_requiem",
                    "feature_ids": [],
                },
                "char_main_dps": {
                    "name": "Main DPS",
                    "combo_id": "template_main_dps",
                    "feature_ids": [],
                },
                "char_buff_support": {
                    "name": "Buff Support",
                    "combo_id": "template_buff_support",
                    "feature_ids": [],
                },
                "char_heal_support": {
                    "name": "Heal Support",
                    "combo_id": "template_heal_support",
                    "feature_ids": [],
                },
                "char_sakiri_support": {
                    "name": "Sakiri Support",
                    "combo_id": "template_sakiri_buff_support",
                    "feature_ids": [],
                },
            },
            "features": {},
            "fixed_team": {
                "enabled": True,
                "slots": [{"char_id": "char_builtin", "combo_id": "char_zero"}],
            },
        }
        with open(self.db_path, "w", encoding="utf-8") as file:
            json.dump(legacy, file)

        database = CustomCharDb(self.db_path, self.features_dir, self.context)

        with open(self.db_path, encoding="utf-8") as file:
            persisted = json.load(file)
        self.assertEqual(persisted["schema_version"], DB_SCHEMA_VERSION)
        self.assertEqual(persisted["characters"]["char_builtin"]["impl_id"], "builtin:zero")
        self.assertEqual(persisted["characters"]["char_custom"]["impl_id"], "combo_text")
        self.assertEqual(persisted["characters"]["char_requiem"]["impl_id"], "builtin:requiem")
        self.assertEqual(
            persisted["characters"]["char_main_dps"]["impl_id"],
            "builtin:template_main_dps",
        )
        self.assertEqual(
            persisted["characters"]["char_buff_support"]["impl_id"],
            "builtin:template_buff_support",
        )
        self.assertEqual(
            persisted["characters"]["char_heal_support"]["impl_id"],
            "builtin:template_heal_support",
        )
        self.assertEqual(
            persisted["characters"]["char_sakiri_support"]["impl_id"],
            "builtin:template_sakiri_buff_support",
        )
        self.assertNotIn("combo_id", persisted["characters"]["char_builtin"])
        self.assertEqual(database.get_fixed_team()["slots"][0]["impl_id"], "builtin:zero")

    def test_builtin_registry_generates_id_from_the_character_module(self):
        entry = char_registry.get("builtin:zero")

        self.assertIsNotNone(entry)
        self.assertIs(entry.char_cls, Zero)
        self.assertEqual(entry.cn_name, "零")

    def test_lw_requiem_is_available_through_the_current_registry(self):
        entry = char_registry.get("builtin:requiem")

        self.assertIsNotNone(entry)
        self.assertIs(entry.char_cls, Requiem)
        self.assertEqual(entry.cn_name, "安魂曲主C")
        self.assertIs(get_char_implementation_class("builtin:requiem"), Requiem)

    def test_lw_zankou_main_dps_is_available_through_the_current_registry(self):
        entry = char_registry.get("builtin:zankou_main_dps")

        self.assertIsNotNone(entry)
        self.assertIs(entry.char_cls, ZankouMainDps)
        self.assertEqual(entry.cn_name, "残虹主C")
        self.assertIs(
            get_char_implementation_class("builtin:zankou_main_dps"),
            ZankouMainDps,
        )

    def test_manager_only_process_bootstraps_lw_registry_before_validation(self):
        isolated_dir = Path(self.temp_dir) / "manager_only"
        isolated_dir.mkdir()
        isolated_db = isolated_dir / "db.json"
        isolated_db.write_text(
            json.dumps(
                {
                    "schema_version": DB_SCHEMA_VERSION,
                    "combos": {},
                    "characters": {
                        "char_zankou": {
                            "name": "残虹",
                            "impl_id": "builtin:zankou_main_dps",
                            "feature_ids": [],
                        },
                        "char_sakiri": {
                            "name": "早雾",
                            "impl_id": "builtin:template_sakiri_buff_support",
                            "feature_ids": [],
                        },
                    },
                    "features": {},
                    "fixed_team": {"enabled": False, "slots": []},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        code = "\n".join(
            (
                "import importlib",
                "import json",
                "import sys",
                "from pathlib import Path",
                "module = importlib.import_module('src.char.custom.CustomCharManager')",
                "root = Path(sys.argv[1])",
                "module.CUSTOM_CHARS_DIR = str(root)",
                "module.FEATURES_DIR = str(root / 'features')",
                "module.EXTERNAL_CHARS_DIR = str(root / 'external_chars')",
                "module.DB_PATH = str(root / 'db.json')",
                "manager = module.CustomCharManager()",
                "assert manager.get_character_impl_id_by_id('char_zankou') == "
                "'builtin:zankou_main_dps'",
                "assert manager.get_character_impl_id_by_id('char_sakiri') == "
                "'builtin:template_sakiri_buff_support'",
                "persisted = json.loads((root / 'db.json').read_text(encoding='utf-8'))",
                "assert persisted['characters']['char_zankou']['impl_id'] == "
                "'builtin:zankou_main_dps'",
                "assert persisted['characters']['char_sakiri']['impl_id'] == "
                "'builtin:template_sakiri_buff_support'",
            )
        )

        result = subprocess.run(
            [sys.executable, "-c", code, str(isolated_dir)],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_external_registry_generates_id_from_class_name(self):
        external_dir = Path(self.temp_dir) / "external_chars"
        external_dir.mkdir()
        (external_dir / "hero.py").write_text(
            "from src.char.BaseChar import BaseChar, Element\n"
            "\n"
            "class FutureHero(BaseChar):\n"
            "    cn_name = '外置英雄'\n"
            "    en_name = 'Future Hero'\n"
            "    element = Element.PURPLE\n",
            encoding="utf-8",
        )

        entry = CharRegistry(external_dir=external_dir).get("external:futurehero")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.source, "external")
        self.assertEqual(entry.char_cls.__name__, "FutureHero")
        self.assertEqual(entry.display_name("zh_CN"), "外置英雄")

    def test_external_registry_rescan_does_not_reload_builtins(self):
        external_dir = Path(self.temp_dir) / "external_chars"
        external_dir.mkdir()
        registry = CharRegistry(external_dir=external_dir)
        builtin_entry = registry.get("builtin:zero")

        (external_dir / "hero.py").write_text(
            "from src.char.BaseChar import BaseChar, Element\n"
            "\n"
            "class FutureHero(BaseChar):\n"
            "    cn_name = '外置英雄'\n"
            "    en_name = 'Future Hero'\n"
            "    element = Element.PURPLE\n",
            encoding="utf-8",
        )

        registry.rescan_external()

        self.assertIs(registry.get("builtin:zero"), builtin_entry)
        self.assertIsNotNone(registry.get("external:futurehero"))


if __name__ == "__main__":
    unittest.main()
