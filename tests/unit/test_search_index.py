from app.search_index import TYPES, Entry, SearchIndex


def make_index() -> SearchIndex:
    index = SearchIndex()
    rows = [
        ("aop", 37, "PPARα activation leading to hepatocellular adenomas", True),
        ("aop", 37, "PPARalpha-dependent liver tumors in rodents", False),
        ("aop", 150, "Liver fibrosis", True),
        ("key_event", 18, "Activation, AhR", True),
        ("key_event", 344, "Liver fibrosis", True),
        ("key_event", 1170, "Increased, hepatocellular proliferation", True),
        ("chemical", "83-79-4", "Rotenone", True),
        ("chemical", "83-79-4", "Derris", False),
        ("chemical", "6659-45-6", "1',2'-Dihydrorotenone", True),
        ("gene", 348, "AHR", True),
    ]
    for type_, entity_id, text, is_title in rows:
        index.entries.setdefault((type_, entity_id), Entry(type_, entity_id)).add(text, is_title)
    index.token = "t"
    return index


def search(query: str, types=TYPES, limit: int = 10):
    hits, total = make_index().search(query, set(types), limit)
    return [(h["type"], h["id"], h["score"]) for h in hits], total


def test_exact_before_prefix_before_word_before_substring():
    hits, total = search("liver fibrosis")
    assert hits[:2] == [("aop", 150, 100), ("key_event", 344, 100)]
    assert total == 2
    assert search("rotenone")[0] == [("chemical", "83-79-4", 100), ("chemical", "6659-45-6", 40)]
    assert search("hepato")[0] == [("key_event", 1170, 60), ("aop", 37, 60)]
    assert search("activation")[0][0] == ("key_event", 18, 80)


def test_synonyms_match_but_title_is_returned():
    hits, _ = make_index().search("derris", set(TYPES), 5)
    assert hits[0]["title"] == "Rotenone" and hits[0]["matched"] == "Derris"
    assert hits[0]["path"] == "/v1/chemicals/83-79-4"


def test_identifier_hits():
    assert search("AOP 37")[0][0] == ("aop", 37, 100)
    assert search("KE18")[0][0] == ("key_event", 18, 100)
    assert search("KER 1229")[0][0] == ("ker", 1229, 100)
    assert search("83-79-4")[0][0] == ("chemical", "83-79-4", 100)
    assert search("HGNC:348")[0][0] == ("gene", 348, 100)
    bare, _ = search("37")
    assert ("aop", 37, 90) in bare
    assert search("AOP 999")[0] == []  # unknown ids are not invented


def test_type_filter_and_limit():
    hits, total = search("liver", types=("key_event",))
    assert [h[0] for h in hits] == ["key_event"]
    limited, total_all = search("liver", limit=1)
    assert len(limited) == 1 and total_all == 3
