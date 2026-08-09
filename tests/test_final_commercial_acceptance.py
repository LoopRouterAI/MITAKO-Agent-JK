# -*- coding: utf-8 -*-
from scripts.run_final_commercial_acceptance import damage_follow_up_consistent


def test_damage_follow_up_consistency_rejects_stale_positive_explanation() -> None:
    assert damage_follow_up_consistent({
        "primary_claim_support": "insufficient",
        "business_follow_up_reason": "开箱合规项未闭环，保留复核信号。",
    })
    assert not damage_follow_up_consistent({
        "primary_claim_support": "supported",
        "business_follow_up_reason": "Evidence is clear and complete; no human intervention required.",
    })
