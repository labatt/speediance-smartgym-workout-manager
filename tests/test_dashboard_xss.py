"""The dashboard builds DOM with innerHTML, so API values must be escaped.

Workout titles are written by Claude through the MCP server, and Claude reads untrusted
input (session notes, saved facts, web pages). Exercise and course names come from
Speediance. None of it is trusted, and all of it lands in a template literal.
"""
import os, re, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Values that come from the API and are interpolated into innerHTML.
API_VALUES = [
    ("dashboard.html", ["p.title", "r.title", "r.exercise", "m.bodyPart", "x.label", "x.value"]),
    ("progress.html", ["row.muscle"]),
]


class TestNoUnescapedApiValues(unittest.TestCase):
    def test_every_api_value_goes_through_esc(self):
        for name, fields in API_VALUES:
            source = open(os.path.join(ROOT, "templates", name)).read()
            self.assertIn("const esc =", source, f"{name} has no escape helper")
            for field in fields:
                bare = re.findall(r"\$\{\s*" + re.escape(field) + r"\s*\}", source)
                self.assertEqual(bare, [], f"{name}: ${{{field}}} is interpolated unescaped")

    def test_the_helper_escapes_the_characters_that_matter(self):
        # Mirrors the JS implementation; a regression in either should fail here.
        source = open(os.path.join(ROOT, "templates", "dashboard.html")).read()
        for char in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
            self.assertIn(char, source, f"escape helper is missing {char}")


if __name__ == "__main__":
    unittest.main()
