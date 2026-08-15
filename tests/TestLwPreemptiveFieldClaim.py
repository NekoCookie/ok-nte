import unittest

from src.combat.planner import FieldClaim
from src.lw.field_claim_ext import (
    LwPreemptiveFieldClaim,
    is_lw_preemptive_field_claim,
    lw_preemptive_field_claim,
)


class TestLwPreemptiveFieldClaim(unittest.TestCase):
    def test_lw_factory_keeps_the_ru_field_claim_contract_unchanged(self):
        claim = lw_preemptive_field_claim("confirmed support resource")

        self.assertIsInstance(claim, FieldClaim)
        self.assertIsInstance(claim, LwPreemptiveFieldClaim)
        self.assertTrue(is_lw_preemptive_field_claim(claim))
        self.assertNotIn("timing", FieldClaim.__dataclass_fields__)
        self.assertFalse(hasattr(FieldClaim, "preemptive"))

    def test_regular_ru_claim_is_not_preemptive(self):
        self.assertFalse(is_lw_preemptive_field_claim(FieldClaim.high("ordinary claim")))


if __name__ == "__main__":
    unittest.main()
