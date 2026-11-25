import pytest

from docbuilder import doc, para

BOLD = {"bold": True, "fontSize": {"magnitude": 10, "unit": "PT"}}
PLAIN = {"fontSize": {"magnitude": 10, "unit": "PT"}}


def resume_elements() -> list[dict]:
    return [
        para("Jane Doe", "TITLE"),
        para("Senior SDET | Test Infrastructure", "SUBTITLE"),
        para("Berlin · jane@example.com"),
        para("GitHub: https://github.com/example"),
        para("SUMMARY", "HEADING_1"),
        para("Senior SDET with 10 years in testing."),
        para("TECHNICAL SKILLS", "HEADING_1"),
        para("", runs=[("Development: ", BOLD), ("Python", PLAIN)]),
        para("Testing: pytest"),
        para("EXPERIENCE", "HEADING_1"),
        para("Acme", "HEADING_2"),
        para("Analytics platform"),
        para("Senior SDET | Oct 2025 - Present", "HEADING_3"),
        para("Own the QA platform used by three teams."),
        para("Built plugin one.", list_id="L1"),
        para("Built plugin two.", list_id="L1"),
        para("Built plugin three.", list_id="L1"),
        para("QA Engineer | Jul 2024 - Oct 2025", "HEADING_3"),
        para("Migrated tests.", list_id="L2"),
        para("Built API tests.", list_id="L2"),
        para("Globex", "HEADING_2"),
        para("QA | 2019 - 2024", "HEADING_3"),
        para("Refactored NUnit tests.", list_id="L3"),
        para("EARLIER EXPERIENCE", "HEADING_1"),
        para("Initech | Tester | 2015 - 2016", "HEADING_2"),
        para("Tested things.", list_id="L4"),
        para("EDUCATION", "HEADING_1"),
        para("University of Somewhere | 2010"),
    ]


@pytest.fixture
def resume_doc() -> dict:
    return doc(*resume_elements())
