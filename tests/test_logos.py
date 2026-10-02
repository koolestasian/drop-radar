import tempfile
import unittest
from pathlib import Path

from radar.logos import LogoResolver, pick
from radar.store import Store


class PickTests(unittest.TestCase):
    def test_only_a_confident_name_match_gets_a_domain(self):
        self.assertEqual(pick("Stripe", [{"name": "Stripe", "domain": "stripe.com"}]), "stripe.com")
        self.assertEqual(pick("The Walt Disney Company", [{"name": "Walt Disney", "domain": "disney.com"}]), "disney.com")
        # a country site for the exact name loses to the global "Anduril Industries"
        self.assertEqual(pick("Anduril", [{"name": "Anduril Industries", "domain": "anduril.com"},
                                          {"name": "Anduril", "domain": "andurilgroup.co.za"}]), "anduril.com")
        # a different company that merely starts the same never matches
        self.assertIsNone(pick("Revel", [{"name": "RevelDigital", "domain": "reveldigital.com"}]))
        self.assertIsNone(pick("Fab2", [{"name": "Fabletics", "domain": "fabletics.com"}]))
        self.assertEqual(pick("Booz Allen", []), "boozallen.com")  # hand-checked override


class ResolverCacheTests(unittest.TestCase):
    def test_a_miss_is_queued_once_resolved_it_is_answered(self):
        store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(store.close)
        logos = LogoResolver(store)
        self.assertIsNone(logos.domain("Stripe"))
        self.assertEqual(logos.pending, {"Stripe"})
        store.set_enrichment("logo:stripe", {"domain": "stripe.com"})
        self.assertEqual(logos.domain("Stripe, Inc."), "stripe.com")


if __name__ == "__main__":
    unittest.main()
