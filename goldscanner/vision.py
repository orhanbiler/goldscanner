"""Score listing photos with Claude vision to decide if an item matches."""

from __future__ import annotations

import base64
import json
import logging

import anthropic

from .client import ShopGoodwillClient
from .models import Item, Score

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
            "description": "True only if it matches the target description overall.",
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
        target_description: str,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5",
        max_images: int = 3,
    ):
        self.sg_client = client
        self.target_description = target_description
        self.model = model
        self.max_images = max_images
        self.anthropic = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def score(self, item: Item) -> Score:
        """Send the item's photos to Claude and return a structured verdict."""
        image_blocks = self._image_blocks(item)
        if not image_blocks:
            return Score(False, 0.0, "No usable images to score.")

        prompt = (
            "You are helping find a very specific kind of jewelry listing.\n\n"
            f"TARGET: {self.target_description}\n\n"
            f'Listing title: "{item.title}"\n\n'
            "Look at the photo(s) and judge whether this listing matches the target. "
            "Be honest about uncertainty — you cannot chemically verify that enamel or "
            "metal is 'really gold' from a photo, so base confidence on visual cues "
            "(styling, hallmarks if visible, gold tone, enamel technique) and the title. "
            "Respond using the required JSON schema."
        )

        content: list[dict] = list(image_blocks)
        content.append({"type": "text", "text": prompt})

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

    def _image_blocks(self, item: Item) -> list[dict]:
        blocks: list[dict] = []
        for url in item.image_urls[: self.max_images]:
            downloaded = self.sg_client.download_image(url)
            if not downloaded:
                continue
            raw, media_type = downloaded
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.standard_b64encode(raw).decode("utf-8"),
                    },
                }
            )
        return blocks
