from tcp_auto.extract.keywords import extract_work_items, item_extent_ft
from tcp_auto.ingest.pdf import ingest_pdf, parse_scale


def test_parse_scale():
    assert parse_scale("SCALE: 1\" = 40'") == 40
    assert parse_scale("1\"=20'-0\"") == 20
    assert parse_scale("SCALE 1:480") == 40
    assert parse_scale("NO SCALE") is None


def test_extracts_construct_and_remove(sample_pdf):
    pages = ingest_pdf(sample_pdf)
    assert pages[0].scale_ft_per_inch == 40
    r = extract_work_items(pages)
    actions = sorted(i.action.value for i in r.items)
    assert actions.count("construct") == 3
    assert actions.count("remove") == 2
    types = {i.device_type for i in r.items}
    assert {"pole", "transformer"} <= types
    # two-line label joined: "CONSTRUCT" + "SPAN #2 PRIMARY"
    assert any("SPAN" in i.label_text for i in r.items)


def test_notes_and_title_block_are_not_work_items(sample_pdf):
    r = extract_work_items(ingest_pdf(sample_pdf))
    labels = " ".join(i.label_text for i in r.items)
    assert "SHALL" not in labels and "STANDARDS" not in labels
    assert r.title_block.job_number == "7654321"
    assert r.title_block.address == "1200 E UNIVERSITY DR"
    assert any("REMOVED MATERIAL" in n for n in r.notes)


def test_extent_uses_scale(sample_pdf):
    pages = ingest_pdf(sample_pdf)
    r = extract_work_items(pages)
    ft = item_extent_ft(r.items, pages[0])
    assert 80 < ft < 140  # labels span ~196 pt = ~109 ft at 1"=40'
