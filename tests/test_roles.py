import unittest

from radar.pipeline.roles import level, track


class RoleTests(unittest.TestCase):
    def test_level_reads_the_title_first_and_an_internship_beats_new_grad(self):
        for title, category, want in [
            ("Software Engineer Intern", "", "intern"),
            ("Summer Internship Program", "", "intern"),
            ("Co-op, Hardware", "", "intern"),
            ("Software Engineer, New Grad", "", "new_grad"),
            ("New College Graduate 2027", "", "new_grad"),
            ("Software Engineer", "Internship", "intern"),  # the category breaks the tie
            ("Software Engineer", "", ""),
            ("International Sales Manager", "", ""),  # "intern" is not a prefix match
            ("Intern, New Grad Program", "", "intern"),
        ]:
            with self.subTest(title=title):
                self.assertEqual(level(title, category), want)

    def test_the_two_misses_seen_live_are_found(self):
        self.assertEqual(level("2027 Grads - Software Engineer"), "new_grad")
        self.assertEqual(level("Early Careers Analyst"), "new_grad")
        self.assertEqual(level("Early Career Analyst"), "new_grad")

    def test_track_takes_the_first_rule_that_matches(self):
        for title, role_track, want in [
            ("Quant Developer Intern", "", "Quant"),
            ("Software Engineer", "", "Software"),
            ("Machine Learning Engineer", "", "AI / ML / Data"),
            ("Mechanical Engineer", "", "Hardware"),
            ("Investment Banking Analyst", "", "Finance"),
            ("Recruiter", "", "Other"),
            ("Recruiter", "Software", "Software"),
        ]:
            with self.subTest(title=title):
                self.assertEqual(track(title, role_track), want)


if __name__ == "__main__":
    unittest.main()
