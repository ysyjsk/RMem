from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_test_set_contract_separates_embedding_pass_from_day1_block() -> None:
    text = (ROOT / "protocol" / "test_set_contract_v1.md").read_text(encoding="utf-8")

    assert "BGE-M3 local embedding qualification passed" in text
    assert "Day 1 remains blocked" in text
    assert "both returned HTTP 400" in text
    assert "provider credential is present" in text
    assert "no provider credential is present" not in text
    assert "unqualified local embedding environment" not in text


def test_qualification_report_records_real_embedding_probe_without_opening_gate() -> None:
    text = (
        ROOT / "artifacts" / "reports" / "protocol_qualification_report_v1.md"
    ).read_text(encoding="utf-8")

    assert "BGE-M3 real-episode probe passed" in text
    assert "Day 1 remains blocked" in text
    assert "No model probe is represented as passed" not in text
    assert "full leaf generation remains forbidden" in text.lower()
    assert "222 passed" in text
    assert "both returned HTTP 400" in text
    assert "credential was loaded from the environment" in text
    assert "credentials were absent" not in text
    assert "after an authorized credential is available" not in text
