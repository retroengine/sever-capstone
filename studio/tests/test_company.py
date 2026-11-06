"""Acme Notes on SEVER-DB: what the company app shows is what the engine returned (Stage 6.2).

Oracles. A §3.4: a stored passage is returned by ``passage()`` byte for byte. A §13.2: no ID,
text or vector of a record is in the database's files in the clear, before or after its deletion.
A §3.4 with §5.4: a deleted record's passage is absent. B: ``sever-verify``, a program sharing no
code with the engine, accepts every receipt (§11.3). A dataset: another user's hit carries the
dataset's own text for that ID. D: the call log lists only calls that ran.
"""

from collections.abc import Iterator

import pytest
from conftest import CFG, WORK

from sever_studio.actions import Studio
from sever_studio.company import Company
from sever_studio.ordinary import Ordinary

NOTES = [
    "My blood pressure was 150 over 95 at the March check-up.",
    "Ask the lawyer about the custody hearing on the 14th.",
    "The shed padlock code is 4471; change it after the party.",
]


@pytest.fixture(scope="module")
def company(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Company]:
    work = WORK / f"test-company-{tmp_path_factory.getbasetemp().name}"
    s = Studio(CFG, "synthetic", work, dev=True, rows=120)
    s.open()
    s.backend.insert_next(120)
    c = Company(s, Ordinary(work / "chroma"))
    yield c
    s.backend.close()
    s.backend.wipe()


def test_company_notes_read_back_byte_for_byte(company: Company) -> None:
    b = company.studio.backend
    notes = company.store_notes("Alice", NOTES)
    assert len(notes) == 3
    for n, text in zip(notes, NOTES, strict=True):
        assert n.lsn is not None
        assert b.live.passage(b.cid, n.rid) == text.encode("utf-8")  # A §3.4
    assert company.notes_of("Alice") == [n.rid for n in notes]


def test_company_retrieve_text_is_the_engines_passage(company: Company) -> None:
    s = company.studio
    company.let_others_write()  # the holding area flushes: her notes become searchable (§7.4)
    got, ans = company.ask(NOTES[1])
    assert got.hits
    for h in got.hits:
        if h.mine:
            assert h.text in NOTES  # A §3.4: her own words, as stored
        else:
            assert h.text == s.corpus.texts[s.corpus.position[h.rid]]  # the dataset's text
    assert got.opened  # §8.1: the engine opened at least one group
    assert not ans.ai or ans.text
    for h in got.hits:
        assert h.text is not None
        assert h.text in ans.sent
    assert s.checklist.ticked("assistant")


def test_company_forget_me_leaves_nothing_and_every_receipt_verifies(company: Company) -> None:
    s = company.studio
    rids = company.notes_of("Alice")
    gone = company.forget("Alice")
    assert sorted(gone.deleted.rids) == sorted(rids)
    assert len(gone.receipts) == 3
    assert all(ok for _, _, ok in gone.receipts)  # B: sever-verify ACCEPT
    b = s.backend
    assert all(b.live.passage(b.cid, r) is None for r in rids)  # A §3.4, §5.4
    assert gone.readable == []
    assert gone.found_by_search == []
    # A §13.2: nothing of hers in the clear, before (encrypted) or after (deleted)
    assert all(f == 0 for f, _ in gone.before.hits.values()), gone.before.hits
    assert all(f == 0 for f, _ in gone.after.hits.values()), gone.after.hits
    assert gone.after.files > 0
    assert gone.clean
    assert s.checklist.ticked("gone")
    assert company.notes_of("Alice") == []


def test_company_chroma_is_measured_beside_it(company: Company) -> None:
    # Chroma's own API forgets her; what its files still hold is measured, never assumed
    company.store_notes("Bob", NOTES[:2])
    c = company.forget("Bob").chroma
    assert c is not None
    assert c.deleted == 2
    assert c.readable == []
    assert c.found_by_query == []
    assert set(c.after.hits) == set(c.before.hits)
    assert company.studio.checklist.ticked("compare")


def test_company_the_call_log_holds_only_calls_that_ran(company: Company) -> None:
    kinds = {c.what for c in company.calls}
    assert kinds <= {
        "insert",
        "insert × many",
        "search",
        "explain_search",
        "passage",
        "delete_user",
    }
    assert {"insert", "search", "passage", "delete_user"} <= kinds
    assert all(c.ms >= 0 and c.result for c in company.calls)


def test_company_engine_state_is_the_engines(company: Company) -> None:
    b = company.studio.backend
    st = company.state()
    assert st["records"] == b.live.stats(b.cid)["N"]
    assert st["log leaves"] == b.live.latest_log_checkpoint().tree_size
