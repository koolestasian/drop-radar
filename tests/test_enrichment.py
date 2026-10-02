import json
import unittest
from types import SimpleNamespace

from radar.legacy import llm_extraction


class ExtractorTests(unittest.TestCase):
    def fake_client(self, payload=None, stop_reason="end_turn"):
        calls = []
        content = [SimpleNamespace(type="text", text=json.dumps(payload))] if payload is not None else []

        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                stop_reason=stop_reason, content=content,
                usage=SimpleNamespace(input_tokens=1200, output_tokens=90),
            )
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
        return client, calls

    def extractor(self, client):
        return llm_extraction.Extractor(["Internship", "Other Opportunity"], ["Software Engineering"], client)

    def test_request_shape_and_validation(self):
        client, calls = self.fake_client({
            "is_opportunity": True, "confidence": 1.4, "organization": "Ramp",
            "title": "Software Engineer Intern", "category": "Made Up", "roles": ["Software Engineering", "Nope"],
            "season": "Summer 2027", "location": "NYC", "deadline": "Oct 15",
        })
        extractor = self.extractor(client)
        facts = extractor.extract("Ramp SWE intern apps open", "https://jobs.ashbyhq.com/ramp/x",
                                  "2026-09-30", {"title": "SWE Intern", "description": "Details"})
        request = calls[0]
        self.assertEqual(request["model"], llm_extraction.MODEL)
        self.assertEqual(request["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", request["betas"])
        self.assertEqual(request["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(request["output_config"]["effort"], "low")
        prompt = request["messages"][0]["content"]
        self.assertIn("<job_page>\nDetails\n</job_page>", prompt)
        self.assertIn('"title": "SWE Intern"', prompt)
        self.assertEqual(facts["confidence"], 1.0)
        self.assertEqual(facts["category"], "")
        self.assertEqual(facts["roles"], ["Software Engineering"])
        self.assertEqual(facts["deadline"], "")
        self.assertEqual(extractor.usage["input_tokens"], 1200)

    def test_refusal_and_bad_json_return_none(self):
        client, _ = self.fake_client(stop_reason="refusal")
        self.assertIsNone(self.extractor(client).extract("text"))
        client, _ = self.fake_client(payload=None)
        self.assertIsNone(self.extractor(client).extract("text"))

    def test_schema_is_strict(self):
        schema = llm_extraction.schema(["A"], ["B"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))


if __name__ == "__main__":
    unittest.main()
