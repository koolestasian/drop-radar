import tempfile
import unittest
from pathlib import Path

from radar.api.app import _ranks
from radar.config import Company, Profile, User, Watchlist
from radar.models import Item
from radar.pipeline import priority
from radar.store import Store


def answer(score, confidence):
    return {"type": "score", "score": score, "confidence": confidence, "legend": {}, "probabilities": {}}


class FakeJev:
    """Stands in for the HTTP call: answers by company name."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, payload, key):
        self.calls.append((payload, key))
        return {"model": "jev-1.13.0", "answers": {
            qid: answer(*self.answers[q["instructions"]["company"]]) for qid, q in payload["questions"].items()}}


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        priority._warned = False

    def learn(self, companies, jev, gate=0.7):
        return priority.learn_tiers(self.store, companies, gate, key="k", post=jev)

    def test_confident_guess_is_cached_with_provenance(self):
        jev = FakeJev({"Acme": (2.9, 0.9)})
        self.assertEqual(self.learn(["Acme"], jev), {"Acme": ("S", 0.9)})
        cached = self.store.get_enrichment(priority.cache_key("Acme"))
        self.assertEqual((cached["tier"], cached["source"], cached["model"], cached["confidence"]),
                         ("S", "jev", "jev-1.13.0", 0.9))
        self.assertIn("checked_at", cached)

    def test_below_the_gate_stores_nothing(self):
        self.assertEqual(self.learn(["Acme"], FakeJev({"Acme": (2.9, 0.4)})), {})
        self.assertIsNone(self.store.get_enrichment(priority.cache_key("Acme")))

    def test_cached_company_is_not_asked_again(self):
        jev = FakeJev({"Acme": (1.0, 0.9)})
        self.learn(["Acme"], jev)
        self.learn(["Acme"], jev)
        self.assertEqual(len(jev.calls), 1)

    def test_dry_run_writes_nothing(self):
        stored = priority.learn_tiers(self.store, ["Acme"], 0.7, key="k", post=FakeJev({"Acme": (0.0, 0.9)}), dry_run=True)
        self.assertEqual(stored, {"Acme": ("C", 0.9)})
        self.assertIsNone(self.store.get_enrichment(priority.cache_key("Acme")))

    def test_missing_key_transport_error_and_bad_answer_fail_open(self):
        self.assertEqual(priority.learn_tiers(self.store, ["Acme"], 0.7, key=""), {})

        def boom(payload, key):
            raise ConnectionError("down")
        self.assertEqual(self.learn(["Acme"], boom), {})
        self.assertEqual(self.learn(["Acme"], lambda payload, key: {"model": "m", "answers": {}}), {})
        self.assertIsNone(self.store.get_enrichment(priority.cache_key("Acme")))

    def test_request_carries_public_postings_only(self):
        self.store.upsert_item(Item(source="s", external_id="1", url="https://a/1", title="Intern", company="Acme",
                                    location="NYC"))
        opp = self.store.item_opportunity_id("s", "1")
        self.store.set_action(opp, "kevin", status="Applied", notes="secret note")
        jev = FakeJev({"Acme": (1.0, 0.9)})
        self.learn(["Acme"], jev)
        payload, key = jev.calls[0]
        self.assertEqual(payload["model"], "jev-latest")
        self.assertEqual(payload["state"], {"Acme": {"postings": [{"title": "Intern", "location": "NYC"}]}})
        self.assertNotIn("secret", str(payload))

    def test_actions_rank_a_company_up_and_beat_jev(self):
        self.store.upsert_item(Item(source="s", external_id="1", url="https://a/1", title="Intern", company="Acme"))
        self.store.set_action(self.store.item_opportunity_id("s", "1"), "kevin", status="Applied")
        self.store.set_enrichment(priority.cache_key("Acme"), {"tier": "C", "source": "jev"})
        self.store.set_enrichment(priority.cache_key("Beta"), {"tier": "S", "source": "jev"})
        ranks = priority.learned_ranks(self.store, "kevin")
        self.assertEqual((ranks["acme"], ranks["beta"]), (2, 3))
        self.assertEqual(priority.learned_ranks(self.store, "someone else")["acme"], 0)  # another user: Jev only

    def test_owner_tier_always_wins(self):
        user = User(id="kevin", watchlist=Watchlist(companies=(
            Company("Acme", "greenhouse", "acme", tier="C"), Company("Beta", "greenhouse", "beta"))),
            profile=Profile(company_tiers={"Gamma": "B"}))
        learned = {"acme": 3, "beta": 3, "gamma": 3}
        self.assertEqual(_ranks(user, learned), {"acme": 0, "beta": 3, "gamma": 1})

    def test_agreement_and_gate(self):
        labels = {"a": "S", "b": "A", "c": "C"}
        guesses = {"a": ("S", 0.9, "m"), "b": ("S", 0.6, "m"), "c": ("A", 0.3, "m")}
        report = priority.agreement(labels, guesses, cutoffs=(0.0, 0.5, 0.8))
        self.assertEqual(report, [(0.0, 3, 1, 2), (0.5, 2, 1, 2), (0.8, 1, 1, 1)])
        self.assertEqual(priority.pick_gate(report), 0.5)
        self.assertIsNone(priority.pick_gate([(0.0, 3, 0, 1)]))


if __name__ == "__main__":
    unittest.main()
