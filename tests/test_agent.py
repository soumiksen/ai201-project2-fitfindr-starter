"""
tests/test_agent.py

Verifies the planning loop branching in run_agent():
  - Happy path: all three tools called, session fully populated.
  - No-results path: early exit after search_listings, suggest_outfit and
    create_fit_card never called, session["error"] set, fit_card is None.

LLM-backed tools (suggest_outfit, create_fit_card) are mocked so these
tests run without a GROQ_API_KEY.
"""
import pytest
from unittest.mock import patch, MagicMock

from agent import run_agent


# ── shared fixtures ───────────────────────────────────────────────────────────

EXAMPLE_WARDROBE = {
    "items": [
        {
            "id": "w_001",
            "name": "Baggy straight-leg jeans, dark wash",
            "category": "bottoms",
            "colors": ["dark blue"],
            "style_tags": ["denim", "streetwear"],
            "notes": None,
        }
    ]
}

EMPTY_WARDROBE = {"items": []}

MOCK_LISTING = {
    "id": "lst_002",
    "title": "Y2K Baby Tee — Butterfly Print",
    "description": "Cute 2000s baby tee with butterfly graphic.",
    "category": "tops",
    "style_tags": ["y2k", "vintage", "graphic tee"],
    "size": "S/M",
    "condition": "excellent",
    "price": 18.0,
    "colors": ["white", "pink"],
    "brand": None,
    "platform": "depop",
}


# ── happy path ────────────────────────────────────────────────────────────────

class TestRunAgentHappyPath:

    def _run_with_mocks(self, query, wardrobe=None):
        """Run run_agent with suggest_outfit and create_fit_card mocked."""
        if wardrobe is None:
            wardrobe = EXAMPLE_WARDROBE
        with patch("agent.suggest_outfit", return_value="Outfit suggestion.") as mock_suggest, \
             patch("agent.create_fit_card", return_value="Fit card caption.") as mock_card:
            session = run_agent(query, wardrobe)
        return session, mock_suggest, mock_card

    def test_error_is_none_on_success(self):
        session, _, _ = self._run_with_mocks("vintage graphic tee under $30")
        assert session["error"] is None

    def test_search_results_populated(self):
        session, _, _ = self._run_with_mocks("vintage graphic tee under $30")
        assert isinstance(session["search_results"], list)
        assert len(session["search_results"]) > 0

    def test_selected_item_is_top_result(self):
        session, _, _ = self._run_with_mocks("vintage graphic tee under $30")
        assert session["selected_item"] == session["search_results"][0]

    def test_outfit_suggestion_stored(self):
        session, _, _ = self._run_with_mocks("vintage graphic tee under $30")
        assert session["outfit_suggestion"] == "Outfit suggestion."

    def test_fit_card_stored(self):
        session, _, _ = self._run_with_mocks("vintage graphic tee under $30")
        assert session["fit_card"] == "Fit card caption."

    def test_suggest_outfit_called_once_with_correct_args(self):
        session, mock_suggest, _ = self._run_with_mocks("vintage graphic tee under $30")
        mock_suggest.assert_called_once()
        call_kwargs = mock_suggest.call_args[1]
        assert call_kwargs["new_item"] == session["selected_item"]
        assert call_kwargs["wardrobe"] == EXAMPLE_WARDROBE

    def test_create_fit_card_called_once_with_correct_args(self):
        session, mock_suggest, mock_card = self._run_with_mocks("vintage graphic tee under $30")
        mock_card.assert_called_once()
        call_kwargs = mock_card.call_args[1]
        assert call_kwargs["outfit"] == "Outfit suggestion."
        assert call_kwargs["new_item"] == session["selected_item"]

    def test_parsed_price_extracted(self):
        session, _, _ = self._run_with_mocks("vintage graphic tee under $30")
        assert session["parsed"]["max_price"] == 30.0

    def test_parsed_size_extracted(self):
        session, _, _ = self._run_with_mocks("90s track jacket size M")
        assert session["parsed"]["size"] == "M"

    def test_parsed_no_price_when_absent(self):
        session, _, _ = self._run_with_mocks("vintage leather jacket")
        assert session["parsed"]["max_price"] is None

    def test_parsed_no_size_when_absent(self):
        session, _, _ = self._run_with_mocks("vintage graphic tee under $30")
        assert session["parsed"]["size"] is None

    def test_empty_wardrobe_still_reaches_fit_card(self):
        session, mock_suggest, mock_card = self._run_with_mocks(
            "vintage graphic tee", wardrobe=EMPTY_WARDROBE
        )
        assert session["error"] is None
        mock_suggest.assert_called_once()
        mock_card.assert_called_once()
        assert session["fit_card"] == "Fit card caption."


# ── no-results / early-exit path ──────────────────────────────────────────────

class TestRunAgentNoResults:

    def test_error_set_on_no_results(self):
        session = run_agent("designer ballgown size XXS under $5", EXAMPLE_WARDROBE)
        assert session["error"] is not None
        assert isinstance(session["error"], str)
        assert len(session["error"]) > 0

    def test_error_message_contains_no_listings(self):
        session = run_agent("designer ballgown size XXS under $5", EXAMPLE_WARDROBE)
        assert "No listings found" in session["error"]

    def test_fit_card_is_none_on_early_exit(self):
        session = run_agent("designer ballgown size XXS under $5", EXAMPLE_WARDROBE)
        assert session["fit_card"] is None

    def test_outfit_suggestion_is_none_on_early_exit(self):
        session = run_agent("designer ballgown size XXS under $5", EXAMPLE_WARDROBE)
        assert session["outfit_suggestion"] is None

    def test_suggest_outfit_not_called_on_early_exit(self):
        with patch("agent.suggest_outfit") as mock_suggest, \
             patch("agent.create_fit_card") as mock_card:
            run_agent("designer ballgown size XXS under $5", EXAMPLE_WARDROBE)
        mock_suggest.assert_not_called()
        mock_card.assert_not_called()

    def test_error_mentions_description(self):
        session = run_agent("zzzquinoa under $3", EXAMPLE_WARDROBE)
        assert "zzzquinoa" in session["error"]

    def test_error_mentions_price_when_provided(self):
        session = run_agent("zzzquinoa under $3", EXAMPLE_WARDROBE)
        assert "$3" in session["error"] or "3" in session["error"]

    def test_error_mentions_size_when_provided(self):
        session = run_agent("zzzquinoa size XS under $3", EXAMPLE_WARDROBE)
        assert "XS" in session["error"]

    def test_search_results_empty_list(self):
        session = run_agent("designer ballgown size XXS under $5", EXAMPLE_WARDROBE)
        assert session["search_results"] == []

    def test_selected_item_is_none(self):
        session = run_agent("designer ballgown size XXS under $5", EXAMPLE_WARDROBE)
        assert session["selected_item"] is None
