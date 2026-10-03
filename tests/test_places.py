import unittest
from unittest import mock

from radar.alerts import NtfyChannel
from radar.pipeline.places import format_location as fmt

# (what a source wrote, what people see) -- every shape here was in the live data
CASES = [
    # United States: "City, ST"
    ("Houston, TX", "Houston, TX"),
    ("San Francisco, California", "San Francisco, CA"),
    ("New York, NY", "New York, NY"),
    ("New York, New York, United States", "New York, NY"),
    ("Washington, DC", "Washington, DC"),
    ("Washington D.C.", "Washington, DC"),
    ("Delaware, OH", "Delaware, OH"),
    ("NYC", "New York, NY"),
    ("SF", "San Francisco, CA"),
    ("LA", "Los Angeles, CA"),
    ("Redmond", "Redmond, WA"),  # no state written: the biggest US city of that name
    ("Boston", "Boston, MA"),
    ("Seattle", "Seattle, WA"),
    ("US-TN-Tullahoma", "Tullahoma, TN"),
    ("USA LA Bossier City", "Bossier City, LA"),
    ("TX-Dallas", "Dallas, TX"),
    ("WI Madison", "Madison, WI"),
    ("Atlanta GA", "Atlanta, GA"),
    ("US-California-Palo Alto", "Palo Alto, CA"),
    ("USA - Georgia - Alpharetta - 30005", "Alpharetta, GA"),
    ("United States, Wisconsin, Milwaukee", "Milwaukee, WI"),
    ("Alpharetta, GA, United States", "Alpharetta, GA"),
    ("United States of America, Rochester, New York", "Rochester, NY"),
    ("TORONTO 02", "Toronto, Canada"),
    ("US-IA-CEDAR RAPIDS-182 ~ 1100 Cimmie Ave Ne ~ BLDG 182", "Cedar Rapids, IA"),
    # everywhere else: "City, Country"
    ("Barcelona, Spain", "Barcelona, Spain"),
    ("Barcelona", "Barcelona, Spain"),
    ("London", "London, United Kingdom"),
    ("Poland - Wroclaw", "Wroclaw, Poland"),
    ("Toronto, ON, Canada", "Toronto, Canada"),
    ("Kitzingen, Bavaria, DEU", "Kitzingen, Germany"),
    ("Gerlingen, BW, Germany", "Gerlingen, Germany"),
    ("Daventry, England, GBR", "Daventry, United Kingdom"),
    ("St Albans, England, United Kingdom", "St Albans, United Kingdom"),
    ("Đồng Nai, Vietnam", "Đồng Nai, Vietnam"),
    ("Hsinchu City, Taiwan", "Hsinchu City, Taiwan"),
    ("KUALA LUMPUR GENERAL OFFICE", "Kuala Lumpur, Malaysia"),
    ("MOUNT-ROYAL (Montreal)", "Montreal, Canada"),
    ("Singapore", "Singapore, Singapore"),
    ("Singapore, SGP", "Singapore, Singapore"),
    # several places, in the order the source listed them
    ("Reston, VA; Plano, TX", "Reston, VA; Plano, TX"),
    ("Pleasant Prairie, WI; Milwaukee, WI; Waukegan, IL", "Pleasant Prairie, WI; Milwaukee, WI; Waukegan, IL"),
    ("Toronto, ON, Canada; Chicago, IL", "Toronto, Canada; Chicago, IL"),
    ("New York; Bethlehem; Holmdel", "New York, NY; Bethlehem, PA; Holmdel, United States"),  # the one stated country settles Holmdel
    ("Remote in USA | Reston, VA | Denver, CO", "Reston, VA; Denver, CO"),
    # how you work is a badge, not part of the place
    ("Hybrid - New York, NY", "New York, NY"),
    ("Houston, TX (Remote)", "Houston, TX"),
    ("El Segundo, CA; United States - Virtual", "El Segundo, CA"),
    ("Remote - United States", "Remote, United States"),
    ("Remote, Pennsylvania; Remote, WA", "Remote, United States"),
    ("Remote, Spain", "Remote, Spain"),
    # only what the text supports: a country or state, never an invented city
    ("United States", "United States"),
    ("Iowa", "Iowa, United States"),
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
        self.assertEqual(fmt("4 locations | Des Moines, IA | Raleigh, NC"), "Des Moines, IA; Raleigh, NC")

    def test_the_push_shows_the_same_format(self):
        sent = {}
        def post(url, json, headers, timeout):
            sent.update(json)
            return mock.Mock(status_code=200)
        with mock.patch("radar.alerts.requests.post", side_effect=post):
            NtfyChannel("topic", server="https://ntfy.example").send(
                {"company": "Stripe", "title": "Intern", "location": "Houston, TX", "items": [], "url": ""}, [], None)
        self.assertIn("Houston, TX", sent["message"])


if __name__ == "__main__":
    unittest.main()
