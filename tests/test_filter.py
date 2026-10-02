"""matches_profile against real titles/locations pulled from live boards and the
SimplifyJobs lists (2026-10-01 audit), for both shipped profiles."""
import unittest
from pathlib import Path

from radar.config import Profile, load_profile
from radar.pipeline.filter import is_us_location, matches_profile

ROOT = Path(__file__).resolve().parent.parent


def opp(title, location="", **fields):
    return {"title": title, "company": "", "location": location, "fields": fields}


class LocationTests(unittest.TestCase):
    CASES = [
        # (location, is_us) -- True US, False non-US, None unknown
        ("San Francisco", True), ("SF", True), ("NYC", True), ("Washington, D.C.", True),
        ("San Francisco, Seattle, New York City", True), ("Kent, Washington", True),
        ("Portland, Oregon", True), ("Chicago Office", True), ("Hybrid - New York, NY", True),
        ("US-SF, US-Seattle, US-NYC", True), ("El Segundo, CA", True), ("San Francisco, Amsterdam", True),
        ("Bellevue, Washington; Mountain View, California", True), ("Remote - US", True),
        ("London", False), ("Toronto, ON, CA", False), ("Toronto, CAN", False), ("IN - Bengaluru", False),
        ("Mexico City, Mexico", False), ("DE-Berlin-Trion Building", False), ("Zurich, CH", False),
        ("Remote-Canada", False), ("Sao Paulo - Brazil", False),
        # a trailing country wins over a city abbreviation inside a foreign name ("chi")
        ("Ho Chi Minh, , Vietnam", False), ("Mexicali, BAJA CALIFORNIA, Mexico", False),
        ("Darlington, County Durham, United Kingdom", False), ("Albuquerque, New Mexico", True),
        ("Durham, NC, United States", True), ("United States-Florida-Melbourne", True),
        # US towns named like foreign cities; the foreign city alone stays foreign
        ("Vienna, VA", True), ("Melbourne, FL", True), ("New London, CT", True), ("Warsaw, IN", True),
        ("Pensacola, FL | Vienna, VA", True), ("Vienna", False), ("Brampton, Ontario, CA", False),
        ("In-Office", None), ("N/A", None), ("", None),
    ]

    def test_table(self):
        for location, expected in self.CASES:
            with self.subTest(location=location):
                self.assertIs(is_us_location(location), expected)


class KevinProfileTests(unittest.TestCase):
    """The shipped config/profile.yaml: CS -- software engineering intern / new grad, US or remote."""

    def setUp(self):
        self.profile = load_profile(ROOT / "config" / "profile.yaml")

    def check(self, cases, **kw):
        for title, location, expected in cases:
            with self.subTest(title=title, location=location):
                ok, reasons = matches_profile(opp(title, location), self.profile, **kw)
                self.assertIs(ok, expected, reasons)

    def test_target_roles_match_in_multi_city_and_bare_city_locations(self):
        self.check([
            ("Software Engineer, Intern (Summer or Winter)", "San Francisco, Seattle, New York City", True),
            ("Software Engineer, New Grad", "San Francisco, Seattle, New York", True),
            ("Software Engineering Internship (Summer 2027)", "El Segundo, CA", True),
            ("Software Engineer (University Grad)", "Menlo Park, CA", True),
            ("Software Engineer, Early Career — Immediate Start", "San Francisco", True),
            ("Software Developer Co-op - Full Stack", "Boston, MA", True),
            ("Software Engineer Intern", "In-Office", True),  # unknown location: don't miss it
        ])

    def test_wrong_country_wrong_track_or_wrong_level_do_not(self):
        self.check([
            ("Software Engineer, Intern", "London", False),
            ("Software Engineer, New Grad", "Toronto, ON, CA", False),
            ("Tax Intern - Summer 2027", "New York, NY, United States", False),
            ("Internal Audit Intern", "Hybrid - New York, NY", False),  # "intern" is not in "Internal"
            ("Accounting Intern", "Hybrid - New York, NY", False),
            ("High School Internship, Software Engineering (Summer 2027)", "Seattle, San Francisco", False),
            ("Senior Software Engineer", "San Francisco", False),
        ])

    def test_a_curated_early_career_list_implies_the_level(self):
        """SimplifyJobs/New-Grad-Positions titles are often just 'Software Engineer 1'."""
        self.check([("Software Engineer 1", "SF", True)], level_implied=True)
        self.check([("Software Engineer 1", "SF", False)])


class FriendProfileTests(unittest.TestCase):
    """The shipped config/friend/profile.yaml: Berkeley Haas -- finance, consulting, strategy, PM."""

    def setUp(self):
        self.profile = load_profile(ROOT / "config" / "friend" / "profile.yaml")

    def check(self, cases):
        for title, location, expected in cases:
            with self.subTest(title=title):
                ok, reasons = matches_profile(opp(title, location), self.profile)
                self.assertIs(ok, expected, reasons)

    def test_business_and_finance_early_career_roles_match(self):
        self.check([
            ("2027 Investment Banking Summer Analyst", "New York, NY", True),
            ("Summer Analyst - Sales & Trading", "New York", True),
            ("Structured Finance Intern - Summer 2027", "New York, NY, United States", True),
            ("Credit Risk Intern", "Hybrid - New York, NY", True),
            ("Associate Consultant Intern", "Boston, MA", True),
            ("Associate Product Manager Intern", "Hybrid - San Francisco, CA", True),
            ("Private Equity Summer Associate", "San Francisco", True),
            ("Finance & Strategy Analyst, New Grad", "SF, SEA, CHI, NYC", True),
        ])

    def test_engineering_and_senior_roles_do_not(self):
        self.check([
            ("Software Engineer Intern", "SF", False),
            ("Mechanical Engineering Intern (Summer 2027)", "El Segundo, CA", False),
            ("Senior Financial Analyst", "NYC", False),
            ("Vice President, Investment Banking", "New York, NY", False),
        ])


class SemanticsTests(unittest.TestCase):
    def test_role_and_level_are_both_required_when_both_are_given(self):
        p = Profile(roles=("software engineer",), keywords=("intern",))
        self.assertTrue(matches_profile(opp("Software Engineer Intern"), p)[0])
        self.assertFalse(matches_profile(opp("Software Engineer"), p)[0])
        self.assertFalse(matches_profile(opp("Marketing Intern"), p)[0])

    def test_either_list_alone_is_enough_when_the_other_is_empty(self):
        self.assertTrue(matches_profile(opp("Marketing Intern"), Profile(keywords=("intern",)))[0])
        self.assertTrue(matches_profile(opp("Software Engineer"), Profile(roles=("software engineer",)))[0])

    def test_terms_match_whole_words_with_plural_and_ing_ship_forms_only(self):
        p = Profile(keywords=("intern",))
        for title, expected in [("Internship", True), ("Interns", True), ("International Tax", False),
                                ("Internal Tools", False)]:
            with self.subTest(title=title):
                self.assertIs(matches_profile(opp(title), p)[0], expected)

    def test_enriched_role_track_and_category_count_toward_the_match(self):
        """An Instagram post's title is often just the first caption line."""
        p = Profile(roles=("software engineer",), keywords=("intern",))
        o = opp("Applications are open!", **{"Role / Track": "Software Engineering", "Category": "Internship"})
        self.assertTrue(matches_profile(o, p)[0])


if __name__ == "__main__":
    unittest.main()
