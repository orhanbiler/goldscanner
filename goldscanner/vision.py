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
        "is_match": {
            "type": "boolean",
            "description": "True only if it matches the target overall.",
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

    def score(self, item: Item) -> Score:
        item_blocks = self._download_blocks(item.image_urls[: self.max_images])
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

        return Score(
            is_match=bool(data.get("is_match")),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            reasoning=str(data.get("reasoning", "")),
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
        parts.append(
            "\nUse the labeled reference photos above (if any) as your guide for what "
            "does and does not count as a match. Be honest about uncertainty — you "
            "cannot chemically verify that enamel or metal is 'really gold' from a "
            "photo, so base confidence on visual cues and the title. "
            "Respond using the required JSON schema."
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
                    "text": "Reference photos that ARE a match (gold-filled enamel bangle):",
                }
            )
            for ex in positives:
                blocks.extend(self._download_blocks([ex["image_url"]]))
        if negatives:
            blocks.append(
                {
                    "type": "text",
                    "text": "Reference photos that are NOT a match:",
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
