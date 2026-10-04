import unittest

from radar.pipeline.pay_estimate import estimate_pay


class MarketPayTests(unittest.TestCase):
    def test_us_roles_use_published_wages_and_name_the_population(self):
        hourly, hourly_basis = estimate_pay("Software Engineer Intern", "San Francisco, CA")
        annual, annual_basis = estimate_pay("Software Engineer, New Grad", "New York, NY")
        self.assertIn("/hr", hourly)
        self.assertIn("/yr", annual)
        self.assertIn("software developers", hourly_basis.lower())
        self.assertIn("US-wide", hourly_basis)
        self.assertIn("2025", annual_basis)
        self.assertTrue(estimate_pay("Software Engineering Intern", "Austin, TX")[0])

    def test_unknown_or_non_us_roles_do_not_get_a_us_estimate(self):
        for title, location in [("Software Engineer Intern", "London, UK"),
                                ("Software Engineer Intern", ""),
                                ("Mission Operations Intern", "San Jose, CA"),
                                ("Software Sales Intern", "San Jose, CA")]:
            with self.subTest(title=title, location=location):
                self.assertEqual(estimate_pay(title, location), ("", ""))


if __name__ == "__main__":
    unittest.main()
