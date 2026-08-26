# Visual Plan v1

Visual Plan v1 is the producer-led handoff from a ChatGPT Project to YT-Visuals. It
contains explicit beat context and recommended manual search phrases. The local app
validates, stores, and displays the plan; it does not interpret narration, invent search
queries, select media, or call an AI service.

The canonical JSON Schema is [`schemas/visual-plan.v1.schema.json`](../schemas/visual-plan.v1.schema.json).
A small valid example is [`examples/visual-plan.v1.json`](../examples/visual-plan.v1.json).

## Validation rules

- `document_type` is `visual_plan` and `contract_version` is `1`.
- Story and beat IDs are stable lowercase editorial identifiers.
- Every plan has at least one beat and every beat has at least one nonempty search query.
- Beat IDs and sequences are unique within the plan.
- `media_preference` is `image`, `video`, or `either`.
- `source_requirement` is `representative` or `exact`.
- Production opportunities are optional. Each requires a narration-specific trigger and
  at least one real `sfx_suggestion` or `edit_suggestion`.

Production opportunities are recommendations only. They must describe a concrete action
or event in the narration, not generic mood, pacing, transition, camera, or directing
instructions. The producer decides whether to use them.

Visual Plan v1 is separate from the legacy Visual Request v1 and automated review
contracts. Existing Visual Request and Visual Review workflows remain supported.
