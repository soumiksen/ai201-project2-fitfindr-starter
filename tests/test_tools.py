"""
tests/test_tools.py

Isolated pytest tests for all three FitFindr tools.
Run with: pytest tests/
"""
import pytest
from unittest.mock import MagicMock, patch

from tools import search_listings, suggest_outfit, create_fit_card


# ── Fixtures / shared data ────────────────────────────────────────────────────

SAMPLE_LISTING = {
    "id": "lst_002",
    "title": "Y2K Baby Tee — Butterfly Print",
    "description": "Super cute early 2000s baby tee with butterfly graphic.",
    "category": "tops",
    "style_tags": ["y2k", "vintage", "graphic tee", "cottagecore"],
    "size": "S/M",
    "condition": "excellent",
    "price": 18.0,
    "colors": ["white", "pink", "purple"],
    "brand": None,
    "platform": "depop",
}

EXAMPLE_WARDROBE = {
    "items": [
        {
            "id": "w_001",
            "name": "Baggy straight-leg jeans, dark wash",
            "category": "bottoms",
            "colors": ["dark blue", "indigo"],
            "style_tags": ["denim", "streetwear", "baggy"],
            "notes": "High-waisted, sits above the hip",
        },
        {
            "id": "w_007",
            "name": "Chunky white sneakers",
            "category": "shoes",
            "colors": ["white"],
            "style_tags": ["sneakers", "chunky", "streetwear"],
            "notes": None,
        },
    ]
}

EMPTY_WARDROBE = {"items": []}

SAMPLE_OUTFIT = (
    "Outfit 1: Pair the Y2K Baby Tee with your Baggy straight-leg jeans "
    "and Chunky white sneakers for a nostalgic Y2K streetwear look."
)


def _make_groq_mock(content: str) -> MagicMock:
    """Return a mock Groq client whose chat.completions.create returns `content`."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = content
    return mock_client


# ── Tool 1: search_listings ───────────────────────────────────────────────────

class TestSearchListings:

    def test_returns_list(self):
        result = search_listings("vintage graphic tee")
        assert isinstance(result, list)

    def test_basic_search_returns_results(self):
        result = search_listings("vintage graphic tee", max_price=30.0)
        assert len(result) > 0

    def test_top_result_is_best_match(self):
        # lst_002 has "vintage", "graphic tee" (2 tokens), "tee" in title → score 3
        # stable sort preserves its position ahead of equal-score items that appear later
        result = search_listings("vintage graphic tee", max_price=30.0)
        assert result[0]["id"] == "lst_002"

    def test_price_filter_respected(self):
        result = search_listings("vintage", max_price=25.0)
        assert len(result) > 0
        for item in result:
            assert item["price"] <= 25.0

    def test_price_filter_exact_boundary_included(self):
        # lst_013 "90s Silk Slip Dress" is exactly $30.00
        result = search_listings("vintage dress", max_price=30.0)
        ids = [r["id"] for r in result]
        assert "lst_013" in ids

    def test_size_filter_case_insensitive(self):
        # lowercase "s/m" should match "S/M" in the data
        result = search_listings("tee", size="s/m")
        assert len(result) > 0
        for item in result:
            assert "s/m" in item["size"].lower()

    def test_size_filter_substring_match(self):
        # "M" is a substring of "S/M", so S/M items should be included
        result = search_listings("tee", size="M")
        assert len(result) > 0
        for item in result:
            assert "m" in item["size"].lower()

    def test_no_results_returns_empty_list_not_exception(self):
        result = search_listings("designer ballgown", max_price=5.0)
        assert result == []

    def test_impossible_size_returns_empty_list(self):
        result = search_listings("jeans", size="XXXXL")
        assert result == []

    def test_no_price_filter_includes_expensive_items(self):
        # lst_022 "90s Leather Bomber" is $75 — should appear with no price cap
        result = search_listings("vintage leather")
        ids = [r["id"] for r in result]
        assert "lst_022" in ids

    def test_result_dicts_have_required_fields(self):
        result = search_listings("vintage", max_price=50.0)
        assert len(result) > 0
        required = {
            "id", "title", "description", "category", "style_tags",
            "size", "condition", "price", "colors", "brand", "platform",
        }
        for item in result:
            assert required.issubset(item.keys())

    def test_zero_keyword_overlap_items_excluded(self):
        # Search for a word that doesn't appear in any listing
        result = search_listings("zzzquinoa")
        assert result == []

    def test_higher_scoring_items_ranked_first(self):
        # lst_002 has 3 matching tokens for "vintage graphic tee"; lst_015 has 2
        result = search_listings("vintage graphic tee", max_price=30.0)
        ids = [r["id"] for r in result]
        if "lst_015" in ids:
            assert ids.index("lst_002") < ids.index("lst_015")


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

class TestSuggestOutfit:

    def test_returns_non_empty_string_with_wardrobe(self):
        with patch("tools._get_groq_client") as mock_get:
            mock_get.return_value = _make_groq_mock(
                "Outfit 1: Pair the tee with the baggy jeans and chunky sneakers."
            )
            result = suggest_outfit(SAMPLE_LISTING, EXAMPLE_WARDROBE)
        assert isinstance(result, str)
        assert len(result.strip()) > 0

    def test_wardrobe_item_names_included_in_prompt(self):
        with patch("tools._get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value.choices[0].message.content = "outfit"
            mock_get.return_value = mock_client
            suggest_outfit(SAMPLE_LISTING, EXAMPLE_WARDROBE)

        prompt = mock_client.chat.completions.create.call_args[1]["messages"][0]["content"]
        assert "Baggy straight-leg jeans, dark wash" in prompt
        assert "Chunky white sneakers" in prompt

    def test_empty_wardrobe_returns_non_empty_string(self):
        with patch("tools._get_groq_client") as mock_get:
            mock_get.return_value = _make_groq_mock(
                "This Y2K tee pairs well with wide-leg denim and chunky sneakers."
            )
            result = suggest_outfit(SAMPLE_LISTING, EMPTY_WARDROBE)
        assert isinstance(result, str)
        assert len(result.strip()) > 0

    def test_empty_wardrobe_does_not_raise(self):
        with patch("tools._get_groq_client") as mock_get:
            mock_get.return_value = _make_groq_mock("General styling advice.")
            try:
                suggest_outfit(SAMPLE_LISTING, EMPTY_WARDROBE)
            except Exception as exc:
                pytest.fail(f"suggest_outfit raised {exc!r} on empty wardrobe")

    def test_empty_wardrobe_prompt_has_no_wardrobe_items(self):
        with patch("tools._get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value.choices[0].message.content = "advice"
            mock_get.return_value = mock_client
            suggest_outfit(SAMPLE_LISTING, EMPTY_WARDROBE)

        prompt = mock_client.chat.completions.create.call_args[1]["messages"][0]["content"]
        # Empty-wardrobe path must not reference the wardrobe fixture's item names
        assert "Baggy straight-leg jeans" not in prompt
        assert "Chunky white sneakers" not in prompt

    def test_llm_response_returned_verbatim(self):
        expected = "Wear it with your dark wash jeans. Looks amazing."
        with patch("tools._get_groq_client") as mock_get:
            mock_get.return_value = _make_groq_mock(expected)
            result = suggest_outfit(SAMPLE_LISTING, EXAMPLE_WARDROBE)
        assert result == expected

    def test_new_item_title_included_in_prompt(self):
        with patch("tools._get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value.choices[0].message.content = "ok"
            mock_get.return_value = mock_client
            suggest_outfit(SAMPLE_LISTING, EXAMPLE_WARDROBE)

        prompt = mock_client.chat.completions.create.call_args[1]["messages"][0]["content"]
        assert SAMPLE_LISTING["title"] in prompt


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

class TestCreateFitCard:

    def test_returns_non_empty_string_on_success(self):
        with patch("tools._get_groq_client") as mock_get:
            mock_get.return_value = _make_groq_mock(
                "Found this Y2K Baby Tee on Depop for $18 and I'm obsessed."
            )
            result = create_fit_card(SAMPLE_OUTFIT, SAMPLE_LISTING)
        assert isinstance(result, str)
        assert len(result.strip()) > 0

    def test_llm_called_with_temperature_09(self):
        with patch("tools._get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value.choices[0].message.content = "cap"
            mock_get.return_value = mock_client
            create_fit_card(SAMPLE_OUTFIT, SAMPLE_LISTING)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs.get("temperature") == pytest.approx(0.9)

    def test_item_details_present_in_prompt(self):
        with patch("tools._get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value.choices[0].message.content = "cap"
            mock_get.return_value = mock_client
            create_fit_card(SAMPLE_OUTFIT, SAMPLE_LISTING)

        prompt = mock_client.chat.completions.create.call_args[1]["messages"][0]["content"]
        assert "Y2K Baby Tee" in prompt
        assert "18" in prompt           # price
        assert "depop" in prompt.lower()  # platform

    def test_empty_outfit_returns_error_string(self):
        result = create_fit_card("", SAMPLE_LISTING)
        assert isinstance(result, str)
        assert result.startswith("Could not generate fit card")

    def test_whitespace_only_outfit_returns_error_string(self):
        result = create_fit_card("   \t\n  ", SAMPLE_LISTING)
        assert isinstance(result, str)
        assert result.startswith("Could not generate fit card")

    def test_empty_outfit_does_not_call_llm(self):
        with patch("tools._get_groq_client") as mock_get:
            create_fit_card("", SAMPLE_LISTING)
        mock_get.assert_not_called()

    def test_empty_outfit_does_not_raise(self):
        try:
            create_fit_card("", SAMPLE_LISTING)
        except Exception as exc:
            pytest.fail(f"create_fit_card raised {exc!r} on empty outfit")

    def test_whitespace_outfit_does_not_raise(self):
        try:
            create_fit_card("   ", SAMPLE_LISTING)
        except Exception as exc:
            pytest.fail(f"create_fit_card raised {exc!r} on whitespace outfit")

    def test_llm_response_returned_verbatim(self):
        expected = "Snagged this on Depop for $18 and I'm never going back to fast fashion."
        with patch("tools._get_groq_client") as mock_get:
            mock_get.return_value = _make_groq_mock(expected)
            result = create_fit_card(SAMPLE_OUTFIT, SAMPLE_LISTING)
        assert result == expected
