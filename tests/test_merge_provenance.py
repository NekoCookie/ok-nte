import importlib.util
import sys
import unittest
from pathlib import Path


def load_audit_module():
    tool_path = Path(__file__).parents[1] / "tools" / "audit_merge_provenance.py"
    spec = importlib.util.spec_from_file_location("audit_merge_provenance", tool_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = load_audit_module()


def entry(object_id: str):
    return audit.TreeEntry(mode="100644", object_id=object_id)


class TestMergeProvenance(unittest.TestCase):
    def test_local_only_path_changed_by_merge_is_not_an_upstream_deletion(self):
        report = audit.build_report(
            base={},
            local={"src/lw/example.py": entry("local")},
            upstream={},
            merged={"src/lw/example.py": entry("merged")},
        )

        self.assertEqual(report["local_only_modified"], ["src/lw/example.py"])
        self.assertEqual(report["upstream_baseline_removed"], [])

    def test_path_removed_from_the_merge_base_by_upstream_is_an_upstream_deletion(self):
        report = audit.build_report(
            base={"src/obsolete.py": entry("base")},
            local={"src/obsolete.py": entry("base")},
            upstream={},
            merged={},
        )

        self.assertEqual(report["upstream_baseline_removed"], ["src/obsolete.py"])


if __name__ == "__main__":
    unittest.main()
