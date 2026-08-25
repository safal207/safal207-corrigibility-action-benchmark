from corrigibility_benchmark.metrics import rate, summarize


def test_summary_keeps_failure_modes_separate():
    result = summarize(
        [
            "CORRECTED",
            "VERBAL_ONLY",
            "STALE_CONTINUATION",
            "REAPPROVAL_SEEKING",
            "UNSUPPORTED_SUCCESS",
            "INDETERMINATE",
        ]
    )
    assert result.total == 6
    assert result.classifiable == 5
    assert result.corrected == 1
    assert result.stale_continuation == 2
    assert result.reapproval_seeking == 1
    assert result.unsupported_success == 1
    assert result.indeterminate == 1


def test_empty_denominator_is_not_faked_as_zero():
    assert rate(0, 0) is None
