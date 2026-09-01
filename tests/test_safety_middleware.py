from verialign.proxy.middleware.safety_middleware import (
    _TOXIC_WORD_RE,
    _luhn_valid,
    _redact_credit_cards,
)


class TestLuhn:
    def test_valid_credit_card(self) -> None:
        assert _luhn_valid("4111111111111111")

    def test_invalid_credit_card(self) -> None:
        assert not _luhn_valid("4111111111111112")

    def test_short_number(self) -> None:
        assert not _luhn_valid("1234")

    def test_long_number(self) -> None:
        assert not _luhn_valid("1" * 30)

    def test_luhn_with_spaces(self) -> None:
        assert _luhn_valid("4111 1111 1111 1111")


class TestRedactCreditCards:
    def test_redacts_valid_card(self) -> None:
        result = _redact_credit_cards("my card 4111 1111 1111 1111")
        assert "[REDACTED_CREDIT_CARD]" in result

    def test_keeps_invalid_number(self) -> None:
        result = _redact_credit_cards("number 1234567890123456")
        assert "1234567890123456" in result

    def test_redacts_card_with_dashes(self) -> None:
        result = _redact_credit_cards("card 4111-1111-1111-1111")
        assert "[REDACTED_CREDIT_CARD]" in result

    def test_keeps_regular_text(self) -> None:
        result = _redact_credit_cards("hello world")
        assert result == "hello world"

    def test_redacts_only_valid_card(self) -> None:
        result = _redact_credit_cards("valid 4111111111111111 invalid 1234567890123456")
        assert "4111111111111111" not in result
        assert "1234567890123456" in result


class TestToxicityWordBoundary:
    def test_standalone_hate_matches(self) -> None:
        assert _TOXIC_WORD_RE.search("you are hate")

    def test_substring_hate_does_not_match(self) -> None:
        assert not _TOXIC_WORD_RE.search("hateful person")

    def test_removed_kill_does_not_match(self) -> None:
        assert not _TOXIC_WORD_RE.search("kill a zombie process")

    def test_removed_die_does_not_match(self) -> None:
        assert not _TOXIC_WORD_RE.search("they will die")

    def test_removed_attack_does_not_match(self) -> None:
        assert not _TOXIC_WORD_RE.search("attack the castle")

    def test_murder_matches(self) -> None:
        assert _TOXIC_WORD_RE.search("he committed murder")

    def test_abuse_matches(self) -> None:
        assert _TOXIC_WORD_RE.search("child abuse")

    def test_torture_matches(self) -> None:
        assert _TOXIC_WORD_RE.search("torture device")
