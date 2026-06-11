"""Score listing photos with Claude vision, steered by user-labeled examples.

This is "training" via few-shot learning: the user's labeled reference photos
(positive / negative) and free-text guidance are injected into every scoring
request so the model learns what they consider a match.
"""

from __future__ import annotations

import base64
import json
import logging

import anthropic

from .client import ShopGoodwillClient
from .models import Item, Score
from .store import LABEL_NEGATIVE, LABEL_POSITIVE, SETTING_GUIDANCE, SeenStore

log = logging.getLogger(__name__)

_SCHEMA = {
    "type": "object",
    "properties": {
        "is_gold_filled_bangle": {
            "type": "boolean",
            "description": "True if this looks like a gold-filled / rolled-gold bangle bracelet.",
        },
        "has_enamel": {
            "type": "boolean",
            "description": "True if the piece appears to have enamel decoration.",
        },
        "is_lot": {
            "type": "boolean",
            "description": "True if this listing is a multi-item jewelry lot rather than a single piece.",
        },
        "gold_type": {
            "type": "string",
            "enum": ["solid_gold", "gold_filled", "gold_plated", "not_gold", "unknown"],
            "description": (
                "Best assessment of the metal from hallmarks, the seller's "
                "description (tested/marked claims), and visual cues."
            ),
        },
        "karat": {
            "type": "string",
            "description": (
                "Karat/fineness if determinable, e.g. '14K', '10K', '1/20 12K GF', "
                "'18K'. Empty string if unknown."
            ),
        },
        "hallmark_read": {
            "type": "string",
            "description": (
                "The exact stamp/hallmark text you can actually READ in the photos "
                "(e.g. '14K', '585', 'HAYWARD 1/20 12K GF'). Empty string if no "
                "stamp is legible."
            ),
        },
        "is_match": {
            "type": "boolean",
            "description": (
                "True if the listing matches the target — for a single piece, the piece "
                "itself; for a lot, true if AT LEAST ONE item visible in the photos "
                "appears to be a matching bangle."
            ),
        },
        "confidence": {
            "type": "number",
            "description": "Confidence 0.0-1.0 that this matches the target.",
        },
        "reasoning": {
            "type": "string",
            "description": "One or two sentences explaining the verdict.",
        },
    },
    "required": [
        "is_gold_filled_bangle",
        "has_enamel",
        "is_lot",
        "gold_type",
        "karat",
        "hallmark_read",
        "is_match",
        "confidence",
        "reasoning",
    ],
    "additionalProperties": False,
}


class VisionScorer:
    def __init__(
        self,
        client: ShopGoodwillClient,
        store: SeenStore,
        target_description: str,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5",
        max_images: int = 3,
        max_examples_each: int = 4,
    ):
        self.sg_client = client
        self.store = store
        self.target_description = target_description
        self.model = model
        self.max_images = max_images
        self.max_examples_each = max_examples_each
        self.anthropic = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        # Cache downloaded example images, keyed by the example-set signature,
        # so we only re-download when the user changes their labels.
        self._ex_signature: tuple | None = None
        self._ex_blocks: list[dict] = []
        self._img_cache: dict[str, dict | None] = {}

    def score(self, item: Item, max_images: int | None = None) -> Score:
        limit = max_images or self.max_images
        item_blocks = self._download_blocks(item.image_urls[:limit])
        if not item_blocks:
            return Score(False, 0.0, "No usable images to score.")

        content: list[dict] = []
        content.extend(self._exemplar_blocks())
        content.append({"type": "text", "text": "Now evaluate THIS listing:"})
        content.extend(item_blocks)
        content.append({"type": "text", "text": self._instructions(item)})

        try:
            resp = self.anthropic.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("vision scoring failed for %s: %s", item.item_id, exc)
            return Score(False, 0.0, f"Scoring error: {exc}")

        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return Score(False, 0.0, "Model returned unparseable output.")

        reasoning = str(data.get("reasoning", ""))
        if data.get("is_lot"):
            reasoning = "[Lot] " + reasoning
        gold_type = str(data.get("gold_type") or "unknown")
        if gold_type not in {"solid_gold", "gold_filled", "gold_plated", "not_gold", "unknown"}:
            gold_type = "unknown"
        return Score(
            is_match=bool(data.get("is_match")),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            reasoning=reasoning,
            gold_type=gold_type,
            karat=(str(data.get("karat") or "").strip() or None),
            hallmark=(str(data.get("hallmark_read") or "").strip() or None),
        )

    # -- prompt building -----------------------------------------------------

    def _instructions(self, item: Item) -> str:
        guidance = self.store.get_setting(SETTING_GUIDANCE, "").strip()
        parts = [
            "You are helping find a very specific kind of jewelry listing.\n",
            f"TARGET: {self.target_description}",
        ]
        if guidance:
            parts.append(f"\nADDITIONAL GUIDANCE FROM THE USER:\n{guidance}")
        parts.append(f'\nThis listing\'s title: "{item.title}"')
        if item.description:
            parts.append(
                f'\nSeller\'s description: """{item.description}"""\n'
                "The description can mention weight, condition, or 'estate/unmarked' "
                "— useful context. But do NOT depend on the seller declaring the "
                "metal: the best finds are real gold that the seller did NOT "
                "identify, so silence about karat is NOT a negative signal."
            )
        parts.append(
            "\nVISUAL GOLD ASSESSMENT — judge the metal from how the piece LOOKS, "
            "the way an experienced gold buyer examines it in hand, NOT from any "
            "karat stamp. A clearly stamped '14K' is the listing everyone already "
            "recognizes; the value is in spotting real gold that is unmarked, so "
            "do NOT require a stamp and do NOT lower confidence when none is "
            "visible. Study the candidate against the user's labeled reference "
            "photos and weigh these tells (zoom into edges, the inner shank, "
            "hinges, raised relief, and the clasp):\n"
            "• WEAR-THROUGH / BRASSING (strongest tell): gold-filled and plated "
            "pieces wear through at high-contact spots — exposing a yellow-brass, "
            "coppery, or silvery base metal underneath. SOLID gold is the same "
            "color all the way through, so worn spots and scratches stay gold.\n"
            "• COLOR IN RECESSES & SCRATCHES: solid gold holds a consistent warm "
            "tone everywhere, even inside scratches and deep in crevices. A "
            "brassier, too-bright, or greyish color in worn vs. unworn areas "
            "signals plating over base metal.\n"
            "• DISCOLORATION: real gold does not tarnish. Green/black/red-copper "
            "discoloration — around the clasp, in crevices, where skin touches — "
            "means base metal is showing (gold-filled/plated). Pink/copper "
            "bleed-through = brass core of gold-filled.\n"
            "• DENTS & CHIPS exposing white/grey/copper metal under a gold skin = "
            "NOT solid gold.\n"
            "• CLASP & FINDINGS: clasp, spring ring, and pins that mismatch the "
            "body's color or wear more heavily often mean gold-filled construction.\n"
            "• SEAMS / HOLLOW TUBING: a faint seam line down a hollow bangle leans "
            "gold-filled.\n"
            "Set gold_type from this VISUAL evidence (solid_gold / gold_filled / "
            "gold_plated / not_gold / unknown) and name the specific tells you saw "
            "in reasoning (e.g. 'warm consistent color inside the shank scratches, "
            "no brassing at the clasp → looks solid'). If a karat stamp happens to "
            "be legible, record it in hallmark_read as supporting evidence only — "
            "its absence is never a negative."
        )
        parts.append(
            "\nIMPORTANT — MULTI-ITEM LOTS: some listings are lots of many jewelry "
            "pieces photographed together. If this is a lot, examine EVERY photo "
            "carefully, including the background and edges, hunting for any bangle "
            "that matches the target. A lot IS a match if at least one matching "
            "bangle appears to be present — set is_lot=true, is_match=true, and say "
            "in your reasoning which photo it's in and where (e.g. 'wide gold bangle "
            "with black scrollwork, photo 2, upper left'). Confidence = how sure you "
            "are that a matching bangle is in the lot."
        )
        parts.append(
            "\nThe user's labeled reference photos above are your STANDARD: the "
            "MATCH set shows the look you want, the NOT-a-match set shows the "
            "look-alikes to reject. Compare this candidate's metal and "
            "construction against them tell-by-tell before deciding. Be honest "
            "about uncertainty — you cannot chemically verify gold from a photo — "
            "so base confidence on how closely the visual tells line up with the "
            "MATCH references. Respond using the required JSON schema."
        )
        return "\n".join(parts)

    def _exemplar_blocks(self) -> list[dict]:
        positives = self.store.list_examples(LABEL_POSITIVE)[: self.max_examples_each]
        negatives = self.store.list_examples(LABEL_NEGATIVE)[: self.max_examples_each]
        signature = (
            tuple(e["image_url"] for e in positives),
            tuple(e["image_url"] for e in negatives),
        )
        if signature == self._ex_signature:
            return self._ex_blocks

        blocks: list[dict] = []
        if positives:
            blocks.append(
                {
                    "type": "text",
                    "text": (
                        "Reference photos the user labeled as a MATCH — study the "
                        "metal color, wear, and construction here; this is the "
                        "look you are hunting for:"
                    ),
                }
            )
            for ex in positives:
                blocks.extend(self._download_blocks([ex["image_url"]]))
        if negatives:
            blocks.append(
                {
                    "type": "text",
                    "text": (
                        "Reference photos the user labeled NOT a match — reject "
                        "look-alikes that resemble these:"
                    ),
                }
            )
            for ex in negatives:
                blocks.extend(self._download_blocks([ex["image_url"]]))

        self._ex_signature = signature
        self._ex_blocks = blocks
        return blocks

    def _download_blocks(self, urls: list[str]) -> list[dict]:
        blocks: list[dict] = []
        for url in urls:
            block = self._image_block(url)
            if block:
                blocks.append(block)
        return blocks

    def _image_block(self, url: str) -> dict | None:
        if url in self._img_cache:
            return self._img_cache[url]
        downloaded = self.sg_client.download_image(url)
        if not downloaded:
            self._img_cache[url] = None
            return None
        raw, media_type = downloaded
        block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(raw).decode("utf-8"),
            },
        }
        self._img_cache[url] = block
        return block
