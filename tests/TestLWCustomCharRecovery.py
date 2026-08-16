import json
import tempfile
import unittest
from pathlib import Path

from src.lw.custom_char_recovery import restore_legacy_template_impl_ids


class TestLWCustomCharRecovery(unittest.TestCase):
    def test_restores_only_blank_template_ids_from_matching_backup_record(self):
        data = {
            "schema_version": 7,
            "characters": {
                "sakiri": {"name": "早雾", "impl_id": ""},
                "requiem": {"name": "安魂曲", "impl_id": "builtin:requiem"},
                "renamed": {"name": "新名称", "impl_id": ""},
            },
        }
        backup = {
            "schema_version": 5,
            "characters": {
                "sakiri": {"name": "早雾", "combo_id": "template_sakiri_buff_support"},
                "requiem": {"name": "安魂曲", "combo_id": "char_requiem"},
                "renamed": {"name": "旧名称", "combo_id": "template_main_dps"},
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            backup_path = Path(directory) / "db.json.pre-v7.bak"
            backup_path.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")
            restored = restore_legacy_template_impl_ids(data, str(backup_path))
            repeated = restore_legacy_template_impl_ids(data, str(backup_path))

        self.assertEqual(restored, ["早雾"])
        self.assertEqual(repeated, [])
        self.assertEqual(
            data["characters"]["sakiri"]["impl_id"],
            "builtin:template_sakiri_buff_support",
        )
        self.assertEqual(data["characters"]["requiem"]["impl_id"], "builtin:requiem")
        self.assertEqual(data["characters"]["renamed"]["impl_id"], "")
