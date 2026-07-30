from scripts.check_minor_refund_144989 import contains_sensitive_public_output


def test_signed_media_url_is_not_mistaken_for_personal_data() -> None:
    report_html = (
        '<img src="http://127.0.0.1:7862/api/review-assets/demo?expires=1785421234567890&amp;signature=abc">'
        '<p>五类材料已齐全，可按现行流程继续。</p>'
    )
    row = {
        "conclusion": "五类材料已齐全，可按现行流程继续。",
        "request_metadata_sha256": "1" * 64,
        "asset_manifest": [{"url": "https://example.test/1785421234567890"}],
    }

    assert not contains_sensitive_public_output(report_html, row)


def test_visible_phone_number_is_detected() -> None:
    assert contains_sensitive_public_output("<p>监护人手机号 13812345678</p>", {})
