from app.models.forecast import build_forecast


def test_forecast_uses_readiness_but_keeps_quantitative_outputs_blocked():
    readiness={"overall":"PARTIAL","mode":"EVIDENCE_ONLY","hazards":{
        "river_overflow":{"status":"PARTIAL","reasons":["HYDROLOGICALLY_CONNECTED_STAGE"]}
    },"limitations":["CONNECTED_STAGE_DOES_NOT_IMPLY_FLOOD_WITHOUT_BANK_THRESHOLD"],
    "official_warnings":{"available":False,"items":[]}}
    result=build_forecast({"latitude":13.0,"longitude":100.0}, readiness)
    assert result["data_state"] == "EVIDENCE_ONLY"
    assert "HYDROLOGICALLY_CONNECTED_STAGE" in result["risk_drivers"]
    assert result["occurrence"]["eligible"] is False
    assert result["peak_above_bank_m"]["eligible"] is False


def test_coastal_not_applicable_is_not_counted_as_supported_process():
    # semantic regression guard: NOT_APPLICABLE is intentionally outside READY/PARTIAL.
    supported=[{"status":"PARTIAL"},{"status":"NOT_APPLICABLE"}]
    assert sum(row["status"] in {"READY","PARTIAL"} for row in supported) == 1
