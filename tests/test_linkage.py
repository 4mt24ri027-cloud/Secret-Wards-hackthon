from wards.contracts import Clues, RecordRef
from wards.linkage import link


def test_shared_id_links_but_name_alone_is_uncertain():
    a = Clues(
        ref=RecordRef("hospital_a.csv", "row:0"),
        names=["Mahesh Chauhan"],
        gov_ids=["SYNTHETIC-ID-001"],
    )
    b = Clues(
        ref=RecordRef("hospital_b.csv", "row:0"),
        names=["M. Chauhan"],
        gov_ids=["SYNTHETIC-ID-001"],
    )
    c = Clues(
        ref=RecordRef("hospital_c.csv", "row:0"),
        names=["Mahesh Chauhan"],
    )

    result = link([a, b, c])

    assert result[a.ref] is not None
    assert result[a.ref] == result[b.ref]
    assert result[c.ref] is None