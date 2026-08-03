from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_test_set_contract_records_the_passed_day1_gate_without_opening_later_gates() -> None:
    text = (ROOT / "protocol" / "test_set_contract_v1.md").read_text(encoding="utf-8")

    assert "BGE-M3 local embedding qualification passed" in text
    assert "Day 1 is passed" in text
    assert "proxy_17897` returned HTTP 200" in text
    assert "public LabForge pricing/status snapshot" in text
    assert "No model, judge, embedding, or" in text
    assert "Day 1 remains blocked" not in text
    assert "both returned HTTP 400" not in text
    assert "no provider credential is present" not in text
    assert "unqualified local embedding environment" not in text


def test_qualification_report_records_real_embedding_probe_without_opening_gate() -> None:
    text = (
        ROOT / "artifacts" / "reports" / "protocol_qualification_report_v1.md"
    ).read_text(encoding="utf-8")

    assert "BGE-M3 real-episode probe passed" in text
    assert "Day 1 is passed" in text
    assert "No model probe is represented as passed" not in text
    assert "full leaf generation remains forbidden" in text.lower()
    assert "375 passed" in text


def test_qualification_report_records_evaluator_parity_without_advancing_repeatability() -> None:
    text = (
        ROOT / "artifacts" / "reports" / "protocol_qualification_report_v1.md"
    ).read_text(encoding="utf-8")

    assert "Evaluator Parity is passed" in text
    assert "evaluator-parity-cdc9dc290e214da2bab361283dd163bd" in text
    assert "gpt-4o-2024-08-06" in text
    assert "unavailable external compatibility limitation" in text
    assert "Judge Repeatability remains pending" in text
    assert "judge-repeatability-4c37b7794c664566a4d9dbfba4ef27f9" in text
    assert "HTTP 403" in text
    assert "zero accepted observations" in text
    assert "no retry, model fallback, or Cache Qualification" in text
    assert "full leaf generation remains forbidden" in text.lower()
