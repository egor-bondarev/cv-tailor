from datetime import date

from cvtailor.naming import doc_name, normalize_company, pick_folder, run_dir_name

DAY = date(2026, 11, 25)


def test_normalize_company():
    assert normalize_company("Acme, Inc.") == normalize_company("ACME inc") == normalize_company("acme") == "acme"
    assert normalize_company("ООО Ромашка") == normalize_company("Ромашка")
    assert normalize_company("Co Op Bank") != normalize_company("Op Bank")
    assert normalize_company("  Big   Corp  ") == "big"


def test_pick_folder_existing():
    assert pick_folder("Acme Inc.", [("f1", "Globex"), ("f2", "ACME")]) == "f2"


def test_pick_folder_none():
    assert pick_folder("Initech", [("f1", "Globex")]) is None


def test_pick_folder_deterministic_among_duplicates():
    folders = [("z9", "acme"), ("a1", "Acme Inc"), ("b2", "Acme")]
    assert pick_folder("acme", folders) == pick_folder("acme", list(reversed(folders))) == "b2"


def test_doc_name_indexes():
    base = "Senior SDET - Acme - 2026-11-25"
    assert doc_name("Senior SDET", "Acme", DAY, set()) == base
    assert doc_name("Senior SDET", "Acme", DAY, {base, base + " (2)"}) == base + " (3)"


def test_run_dir_name_cyrillic():
    assert run_dir_name("Яндекс", DAY, set()) == "2026-11-25_яндекс"
    assert run_dir_name("Acme Inc.", DAY, {"2026-11-25_acme-inc"}) == "2026-11-25_acme-inc-2"
