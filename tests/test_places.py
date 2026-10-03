import unittest
from unittest import mock

from radar.alerts import NtfyChannel
from radar.pipeline.places import format_location as fmt

# (what a source wrote, what people see) -- every shape here was in the live data
CASES = [
    ("Houston, TX", "Houston - United States"),
    ("San Francisco, California", "San Francisco - United States"),
    ("New York, NY", "New York - United States"),
    ("New York, New York, United States", "New York - United States"),
    ("Washington, DC", "Washington - United States"),
    ("NYC", "New York - United States"),
    ("SF", "San Francisco - United States"),
    ("Redmond", "Redmond - United States"),
    ("Boston", "Boston - United States"),
    ("London", "London - United Kingdom"),
    ("Poland - Wroclaw", "Wroclaw - Poland"),
    ("US-TN-Tullahoma", "Tullahoma - United States"),
    ("USA LA Bossier City", "Bossier City - United States"),
    ("TX-Dallas", "Dallas - United States"),
    ("WI Madison", "Madison - United States"),
    ("Atlanta GA", "Atlanta - United States"),
    ("US-California-Palo Alto", "Palo Alto - United States"),
    ("USA - Georgia - Alpharetta - 30005", "Alpharetta - United States"),
    ("United States, Wisconsin, Milwaukee", "Milwaukee - United States"),
    ("Alpharetta, GA, United States", "Alpharetta - United States"),
    ("Toronto, ON, Canada", "Toronto - Canada"),
    ("Kitzingen, Bavaria, DEU", "Kitzingen - Germany"),
    ("Gerlingen, BW, Germany", "Gerlingen - Germany"),
    ("Daventry, England, GBR", "Daventry - United Kingdom"),
    ("St Albans, England, United Kingdom", "St Albans - United Kingdom"),
    ("Đồng Nai, Vietnam", "Đồng Nai - Vietnam"),
    ("Hsinchu City, Taiwan", "Hsinchu City - Taiwan"),
    ("KUALA LUMPUR GENERAL OFFICE", "Kuala Lumpur - Malaysia"),
    ("MOUNT-ROYAL (Montreal)", "Montreal - Canada"),
    ("TORONTO 02", "Toronto - Canada"),
    ("US-IA-CEDAR RAPIDS-182 ~ 1100 Cimmie Ave Ne ~ BLDG 182", "Cedar Rapids - United States"),
    ("Singapore", "Singapore - Singapore"),
    ("Singapore, SGP", "Singapore - Singapore"),
    # several places: grouped by country, in the order the source listed them
    ("Reston, VA; Plano, TX", "Reston, Plano - United States"),
    ("Pleasant Prairie, WI; Milwaukee, WI; Waukegan, IL", "Pleasant Prairie, Milwaukee, Waukegan - United States"),
    ("Toronto, ON, Canada; Chicago, IL", "Toronto - Canada; Chicago - United States"),
    ("New York; Bethlehem; Holmdel", "New York, Bethlehem, Holmdel - United States"),  # the one stated country settles the small towns
    ("Remote in USA | Reston, VA | Denver, CO", "Reston, Denver - United States"),
    # how you work is a badge, not part of the place
    ("Hybrid - New York, NY", "New York - United States"),
    ("Houston, TX (Remote)", "Houston - United States"),
    ("El Segundo, CA; United States - Virtual", "El Segundo - United States"),
    ("Remote - United States", "Remote - United States"),
    ("Remote, Pennsylvania; Remote, WA", "Remote - United States"),
    # only what the text supports: a country or state, never an invented city
    ("United States", "United States"),
    ("Iowa", "United States"),
    ("China", "China"),
    # nothing to place
    ("4 locations", ""),
    ("3 Locations | ", ""),
    ("", ""),
    ("   ", ""),
]


class FormatLocationTests(unittest.TestCase):
    def test_every_shape_seen_in_the_live_data(self):
        for raw, shown in CASES:
            with self.subTest(raw=raw):
                self.assertEqual(fmt(raw), shown)

    def test_a_count_followed_by_names_keeps_the_names(self):
        self.assertEqual(fmt("4 locations | Des Moines, IA | Raleigh, NC"), "Des Moines, Raleigh - United States")

    def test_the_push_shows_the_same_format(self):
        sent = {}
        def post(url, json, headers, timeout):
            sent.update(json)
            return mock.Mock(status_code=200)
        with mock.patch("radar.alerts.requests.post", side_effect=post):
            NtfyChannel("topic", server="https://ntfy.example").send(
                {"company": "Stripe", "title": "Intern", "location": "Houston, TX", "items": [], "url": ""}, [], None)
        self.assertIn("Houston - United States", sent["message"])


if __name__ == "__main__":
    unittest.main()
