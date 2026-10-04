import unittest

from radar.pipeline.pay import make_pay, pay_from_json_ld, pay_from_text, period_of, show


class PayFromTextTests(unittest.TestCase):
    def shown(self, text):
        return show(pay_from_text(text))

    def test_ranges_as_postings_write_them(self):
        for text, expected in [
            ("The base salary range for this role is $120,000 - $165,000 USD per year.", "$120,000–$165,000/yr"),
            ("Pay: $62 - $72 per hour", "$62–$72/hr"),
            ("The hourly rate is $45.50 to $60.00 an hour.", "$45.50–$60/hr"),
            ("Compensation: $120K–$150K annually", "$120,000–$150,000/yr"),
            ("<p>Salary range: <strong>$95,000</strong> &ndash; <strong>$110,000</strong></p>", "$95,000–$110,000/yr"),
            ("Annual salary of USD 90,000-110,000", "$90,000–$110,000/yr"),
            ("Pay range £30,000 – £40,000 a year", "£30,000–£40,000/yr"),
            ("This internship pays $38 - $44/hr depending on location", "$38–$44/hr"),
            ("&lt;p&gt;The expected pay range is $20 - $24 per hour&lt;/p&gt;", "$20–$24/hr"),  # Greenhouse escapes twice
            ("between $130,000 and $150,000", "$130,000–$150,000/yr"),  # a yearly-sized amount needs no period word
        ]:
            with self.subTest(text=text):
                self.assertEqual(self.shown(text), expected)

    def test_regions_widen_the_range(self):
        text = "Pay range in CA, NY: $140,000 - $170,000 per year. Pay range elsewhere: $120,000 - $150,000 per year."
        self.assertEqual(self.shown(text), "$120,000–$170,000/yr")

    def test_things_that_are_not_pay_are_not_read(self):
        for text in [
            "A $25,000 sign-on bonus for pharmacists",                      # one amount
            "Sign-on bonus of $5,000 - $10,000",                             # a bonus
            "We raised $50 - $100 million from investors",                   # company money
            "401(k) match of $2,000 - $3,000",                               # a benefit
            "Earn a $1,500 - $2,000 relocation stipend",                     # relocation
            "Pay: $15 - $90 per hour",                                       # not a range anyone means
            "Ages 18-25, 2026-2027 cohort, 10-12 weeks",                     # no currency mark
            "Prizes from $10 - $12 gift cards",                              # too small for a year, no hourly word
            "Located at 1,200 - 1,500 square feet",
            "",
        ]:
            with self.subTest(text=text):
                self.assertEqual(self.shown(text), "")


class StructuredPayTests(unittest.TestCase):
    def test_make_pay_checks_plausibility_for_the_period(self):
        self.assertEqual(show(make_pay(20, 24, "USD", "hr")), "$20–$24/hr")
        self.assertEqual(show(make_pay(120000, 165000, "USD", "")), "$120,000–$165,000/yr")  # size decides
        self.assertIsNone(make_pay(20, 24, "USD", ""))             # unstated and not yearly-sized
        self.assertIsNone(make_pay(120000, 165000, "USD", "hr"))   # an hourly rate of $120,000
        self.assertIsNone(make_pay(50, 40, "USD", "hr"))
        self.assertEqual(show(make_pay(5000, 5000, "USD", "mo")), "$5,000/mo")

    def test_periods_as_sources_name_them(self):
        for word, expected in [("per-year-salary", "yr"), ("HOUR", "hr"), ("HOURLY", "hr"), ("Annual", "yr"),
                               ("MONTH", "mo"), ("per-hour-wage", "hr"), ("", ""), (None, "")]:
            self.assertEqual(period_of(word), expected, word)

    def test_json_ld_base_salary(self):
        posting = {"baseSalary": {"@type": "MonetaryAmount", "currency": "USD",
                                  "value": {"@type": "QuantitativeValue", "minValue": 62, "maxValue": 72, "unitText": "HOUR"}}}
        self.assertEqual(show(pay_from_json_ld(posting)), "$62–$72/hr")
        self.assertIsNone(pay_from_json_ld({"baseSalary": None}))
        self.assertIsNone(pay_from_json_ld({}))


if __name__ == "__main__":
    unittest.main()
