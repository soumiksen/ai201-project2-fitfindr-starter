# FitFindr

A thrift-shopping agent that takes a natural-language search query, finds matching secondhand listings, suggests outfits using the user's wardrobe, and generates a shareable OOTD caption — all in one planning loop.

## Setup

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root with your Groq API key (free at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

Run the Gradio UI:
```bash
python app.py
```

Run the tests:
```bash
pytest tests/
```

---

## Tool Inventory

### Tool 1 — `search_listings`

**Purpose:** Searches the mock listings dataset (`data/listings.json`) for secondhand items that match a natural-language description, an optional size filter, and an optional price ceiling. Returns results ranked by keyword relevance.

**Inputs:**

| Parameter | Type | Description |
|---|---|---|
| `description` | `str` | Natural-language keywords describing the item (e.g. `"vintage graphic tee"`). Scored by token overlap against each listing's `title`, `description`, and `style_tags`. |
| `size` | `str \| None` | Size string to filter by. Case-insensitive substring match — `"M"` matches `"S/M"`. Pass `None` to skip size filtering. |
| `max_price` | `float \| None` | Maximum price in USD, inclusive (`price <= max_price`). Pass `None` to skip price filtering. |

**Output:** `list[dict]` — matching listing dicts sorted by relevance score descending (highest at index 0). Returns an **empty list** if nothing matches; never raises.

Each dict has these fields:
```
id (str), title (str), description (str), category (str),
style_tags (list[str]), size (str), condition (str),
price (float), colors (list[str]), brand (str | None), platform (str)
```

---

### Tool 2 — `suggest_outfit`

**Purpose:** Calls the Groq LLM (llama-3.3-70b-versatile) to suggest 1–2 complete outfit combinations pairing the thrifted item with the user's wardrobe. Falls back to general styling advice when the wardrobe is empty.

**Inputs:**

| Parameter | Type | Description |
|---|---|---|
| `new_item` | `dict` | A full listing dict as returned by `search_listings`. The tool uses `title`, `category`, `style_tags`, and `colors` to build the prompt. |
| `wardrobe` | `dict` | A wardrobe dict with an `"items"` key containing a list of wardrobe item dicts (each with `name`, `category`, and optionally `notes`). An empty wardrobe looks like `{"items": []}`. |

**Output:** `str` — a non-empty string with outfit suggestions. If the wardrobe is non-empty, it references specific wardrobe pieces by their `name`. If empty, it provides general styling advice (silhouettes, shoe types, accessories that pair well with the item). Never returns an empty string and never raises.

---

### Tool 3 — `create_fit_card`

**Purpose:** Calls the Groq LLM at temperature 0.9 to generate a 2–4 sentence Instagram/TikTok-style OOTD caption for the thrifted find. The caption is casual and authentic, mentioning the item name, price, and platform once each.

**Inputs:**

| Parameter | Type | Description |
|---|---|---|
| `outfit` | `str` | The outfit suggestion string returned by `suggest_outfit`. Provides styling context so the caption references the actual look. |
| `new_item` | `dict` | The listing dict for the thrifted item. The tool uses `title`, `price`, and `platform`. |

**Output:** `str` — a 2–4 sentence OOTD caption. If `outfit` is empty or whitespace-only, returns the error string `"Could not generate fit card: outfit description is missing. Ensure suggest_outfit ran successfully first."` without raising.

---

## Planning Loop

`run_agent()` in `agent.py` executes a **fixed linear sequence** — no LLM drives the loop itself. Each step fires unconditionally as long as the previous step succeeded. The only branching is an early-exit gate after `search_listings`.

```
1. PARSE the query
   ─ Regex extracts max_price, size, and description from the raw user query.
   ─ session["parsed"] = {"description": ..., "size": ..., "max_price": ...}

2. CALL search_listings(description, size, max_price)
   ─ session["search_results"] = [...]
   ─ If results == []:
       session["error"] = actionable message
       return session  ← EARLY EXIT; suggest_outfit and create_fit_card never called

3. SELECT top result
   ─ session["selected_item"] = session["search_results"][0]

4. CALL suggest_outfit(new_item=selected_item, wardrobe=session["wardrobe"])
   ─ session["outfit_suggestion"] = LLM response string

5. CALL create_fit_card(outfit=outfit_suggestion, new_item=selected_item)
   ─ session["fit_card"] = LLM caption string

6. RETURN session
   ─ session["error"] is None on success
```

**How the loop knows it is done:** `create_fit_card` always returns a string, so when it completes the pipeline is finished. There is no iteration — each tool is called exactly once per `run_agent()` invocation.

**Query parsing detail:** Regex, not an LLM, parses the user's query. Two patterns run in sequence:
- `re.search(r'under \$?(\d+(?:\.\d+)?)', query, re.IGNORECASE)` → captures the price ceiling
- `re.search(r'\b(XXS|XS|S/M|S|M|L|XL|XXL|W\d+)\b', query, re.IGNORECASE)` → captures the size token

The description is what remains after those tokens are stripped and whitespace is collapsed. This approach is deterministic (no API call, no latency) and fully testable.

---

## State Management

All state lives in the `session` dict created by `_new_session()`. Nothing is stored in module-level globals — every tool receives only what it needs, pulled from `session` by the planning loop. Tools are pure functions with respect to state; the loop wires them together.

| Key | Type | Set by | Read by |
|---|---|---|---|
| `query` | `str` | `_new_session()` | parse step |
| `parsed` | `dict` `{description, size, max_price}` | parse step | `search_listings` call + error message |
| `search_results` | `list[dict]` | loop after Tool 1 | empty-check + item selection |
| `selected_item` | `dict \| None` | loop after empty-check | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | `dict` | `_new_session()` | `suggest_outfit` |
| `outfit_suggestion` | `str \| None` | loop after Tool 2 | `create_fit_card` |
| `fit_card` | `str \| None` | loop after Tool 3 | caller (`app.py`, CLI) |
| `error` | `str \| None` | loop on early exit | caller |

The wardrobe dict is passed into `run_agent()` by the caller and stored unchanged in `session["wardrobe"]`. It is never mutated. The Gradio UI (`app.py`) selects between `get_example_wardrobe()` and `get_empty_wardrobe()` based on the radio button, then hands the result to `run_agent()`.

---

## Error Handling

### Per-tool failure modes

**`search_listings` — no matching results**

When all listings are filtered out by price, size, or keyword scoring, the function returns `[]`. The planning loop checks `len(session["search_results"]) == 0` immediately and sets:

```python
session["error"] = (
    "No listings found for 'designer ballgown' in size XXS under $5. "
    "Try broadening your search — remove the size filter or raise your price limit."
)
return session
```

`suggest_outfit` and `create_fit_card` are never called. Both `session["outfit_suggestion"]` and `session["fit_card"]` remain `None`. The Gradio UI surfaces the error string in the first output panel with the other two panels left blank.

**Concrete test example:** `run_agent("designer ballgown size XXS under $5", wardrobe)` — this query is deliberately included as one of the Gradio example prompts. The test `test_error_message_contains_no_listings` confirms `"No listings found"` appears in `session["error"]`, and `test_fit_card_is_none_on_early_exit` confirms `session["fit_card"] is None`.

---

**`suggest_outfit` — empty wardrobe**

When `wardrobe["items"]` is an empty list, the tool switches prompt branches internally rather than raising. The LLM receives a prompt asking for general styling advice (silhouettes, shoe types, accessories) rather than specific wardrobe outfit combos. The planning loop continues normally — this is not treated as an error and `session["error"]` remains `None`.

**Concrete test example:** `suggest_outfit(SAMPLE_LISTING, {"items": []})` with the Groq client mocked. The test `test_empty_wardrobe_prompt_has_no_wardrobe_items` asserts that neither `"Baggy straight-leg jeans"` nor `"Chunky white sneakers"` appear in the LLM prompt (the general-advice path is taken), while `test_empty_wardrobe_returns_non_empty_string` asserts the returned string is non-empty. The agent test `test_empty_wardrobe_still_reaches_fit_card` verifies the entire pipeline completes successfully with an empty wardrobe.

---

**`create_fit_card` — empty or whitespace-only outfit string**

If `suggest_outfit` somehow returned an empty string, `create_fit_card` guards at the top of the function:

```python
if not outfit or not outfit.strip():
    return "Could not generate fit card: outfit description is missing. Ensure suggest_outfit ran successfully first."
```

No LLM call is made and no exception is raised. The planning loop stores this string in `session["fit_card"]`.

**Concrete test example:** `create_fit_card("", SAMPLE_LISTING)` and `create_fit_card("   \t\n  ", SAMPLE_LISTING)`. The tests `test_empty_outfit_returns_error_string` and `test_whitespace_only_outfit_returns_error_string` both assert the return value starts with `"Could not generate fit card"`. `test_empty_outfit_does_not_call_llm` additionally confirms `_get_groq_client` is never called on the empty-outfit path, which means there is zero API cost or latency for this failure mode.

---

## Interaction Walkthrough

**User query:** `"90s track jacket in size M"`

**Step 1 — Parse**
- Tool: regex parser in `run_agent()`
- Input: raw query string `"90s track jacket in size M"`
- Why: deterministic parsing with no API latency; extracts `size="M"`, `max_price=None`, `description="90s track jacket"`
- Output: `session["parsed"] = {"description": "90s track jacket", "size": "M", "max_price": None}`

**Step 2 — `search_listings`**
- Tool: `search_listings`
- Input: `description="90s track jacket"`, `size="M"`, `max_price=None`
- Why: retrieves and ranks matching items from the 40-listing dataset before any LLM is involved
- Output: list of matching listing dicts sorted by token-overlap score; `session["search_results"]` is non-empty so the loop continues

**Step 3 — `suggest_outfit`**
- Tool: `suggest_outfit`
- Input: `new_item = session["selected_item"]` (top result), `wardrobe = get_example_wardrobe()`
- Why: uses the Groq LLM to combine the item's style context with the user's actual wardrobe pieces into named outfit combos
- Output: a string like `"Outfit 1: Layer the track jacket over your Ribbed white crop top with the High-waisted wide-leg trousers and your Chunky white sneakers — clean 90s athleisure. Outfit 2: Throw it over the Oversized band tee with your Baggy straight-leg jeans and Black combat boots for a grungier take."`

**Step 4 — `create_fit_card`**
- Tool: `create_fit_card`
- Input: `outfit = session["outfit_suggestion"]`, `new_item = session["selected_item"]`
- Why: the LLM condenses the full outfit suggestion into a 2–4 sentence social caption; temperature 0.9 ensures variation across runs
- Output: `"Grabbed this 90s Colorblock Track Jacket on Poshmark for $32 and it's the piece I didn't know my wardrobe needed. Wide-leg trousers and chunky sneakers, done — the look just locked in. Thrifting a decade's aesthetic for under $35 never gets old."`

**Final output to user:** The Gradio UI populates three panels — the listing details card (title, price, platform, size, condition, brand, colors, style tags), the outfit suggestion, and the fit card caption. `session["error"]` is `None`.

---

## Spec Reflection

**One way planning.md helped during implementation:**

The State Management table in `planning.md` — which maps every session key to what sets it and what reads it — was the most directly useful artifact during implementation. When writing `run_agent()`, the table made it immediately clear which values to pull from `session` at each step and where to store each tool's output, eliminating any ambiguity about data flow. It also served as a checklist: once I'd confirmed every row was satisfied, the loop was complete. Without that table I would have had to reverse-engineer the data flow from the tool signatures, which is slower and more error-prone.

**One divergence from your spec, and why:**

The spec's Planning Loop section listed the size regex as `r'\b(XXS|XS|S/M|S|M|L|XL|XXL|W\d+.*|one[- ]size)\b'`, but the implementation uses `r'\b(XXS|XS|S/M|S|M|L|XL|XXL|W\d+)\b'` — dropping the `one[-]size` alternative and removing the trailing `.*` from the `W\d+` pattern. The `one size` alternative was removed because it does not appear in `listings.json` and the `.*` suffix on `W\d+` was too greedy: in a query like `"W30 under $40"` it would consume `"W30 under"`, breaking the description after price-stripping. The narrower pattern is safer and passes all test cases including `test_parsed_size_extracted`.

---

## AI Usage

### Instance 1 — Tool 2 implementation (`suggest_outfit`)

**Input given to Claude Code:**
I pasted the full Tool 2 section from `planning.md` — both prompt branches (wardrobe present vs. empty), the return-string format guarantees, the "never empty, never raises" contract, and the `wardrobe_schema.json` item structure showing the `name`, `category`, and `notes` fields. I also included the `_get_groq_client()` helper already present in `tools.py` so Claude would use the existing client pattern rather than invent a new one.

**What it produced:**
A complete `suggest_outfit()` implementation that checked `wardrobe.get("items")` for emptiness, built two distinct prompt strings (one listing wardrobe items by name using a join, one requesting general styling advice), and called `client.chat.completions.create` with `model="llama-3.3-70b-versatile"`. The structure matched the spec almost exactly on first generation.

**What I changed before using it:**
The initial prompt for the non-empty wardrobe path formatted wardrobe items as a bullet list using `item["name"]` only. I overrode this to also append `item.get("notes")` inline when notes exist (e.g. `"Baggy straight-leg jeans, dark wash: High-waisted, sits above the hip"`), because the spec said the LLM should reference pieces "by name" and I wanted it to have styling context beyond just the name. I also changed the system-level framing from `"You are a helpful assistant"` to `"You are a fashion stylist"` for tonal consistency with Tool 3's prompt.

---

### Instance 2 — Planning loop implementation (`run_agent`)

**Input given to Claude Code:**
I gave Claude the complete Planning Loop section of `planning.md` (the full numbered pseudocode block with the early-exit condition spelled out), the State Management table, and the `_new_session()` function that was already in `agent.py`. I also included the Mermaid architecture diagram from `planning.md` to clarify the wardrobe-empty branch inside `suggest_outfit` so Claude wouldn't add a second branch in the loop itself.

**What it produced:**
A correct `run_agent()` with regex parsing, the `search_listings` call, the empty-results early exit, item selection at index 0, and both LLM tool calls. The initial output used `re.search(r'under \$?(\d+)', ...)` for the price regex (missing the decimal group `(?:\.\d+)?`) and used a trailing `.*` on the size pattern as noted in the Spec Reflection section above.

**What I changed before using it:**
I corrected the price regex to `r'under \$?(\d+(?:\.\d+)?)'` to handle prices like `$29.99`. I narrowed the size regex to remove `one[-]size` and the trailing `.*` from `W\d+` as described in the Spec Reflection. I also added the description-cleaning step more carefully — stripping the matched price span by using `price_match.start()` and `price_match.end()` as slice indices rather than a second `re.sub`, which produced cleaner results when the price token appeared mid-sentence. These were targeted surgical edits to a correct structural skeleton rather than rewrites.
