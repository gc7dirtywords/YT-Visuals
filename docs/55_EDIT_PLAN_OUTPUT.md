# Edit Plan v1 Output Contract

Edit Plan v1 is created **after** the producer has selected the actual media for the story.

Input should include a current YT-ChannelOps storyboard that shows the selected visual for every beat being planned.

When the user asks for an Edit Plan, return ONLY valid UTF-8 JSON matching this contract. Do not wrap it in Markdown fences or add commentary unless explicitly requested.

## Purpose

Edit Plan v1 carries Project editorial recommendations for:
- visual motion treatment;
- the transition from each beat to the next.

YT-ChannelOps stores the recommendation and the producer's eventual choice separately.

The Project decides. YT-ChannelOps does not infer.

## Top-level shape

```json
{
  "document_type": "edit_plan",
  "contract_version": 1,
  "story": {
    "story_id": "same-story-id"
  },
  "beats": []
}
```

No additional top-level properties are allowed.

## Beat shape

Every beat contains:

```json
{
  "beat_id": "beat-001",
  "sequence": 1,
  "motion_recommendation": {
    "type": "slow_zoom_in",
    "purpose": "Why this treatment helps the actual selected visual and narration.",
    "target": "doorway"
  },
  "transition_out_recommendation": {
    "type": "cross_dissolve",
    "to_beat_id": "beat-002",
    "purpose": "Why this boundary should dissolve rather than cut."
  }
}
```

For the final beat:

```json
"transition_out_recommendation": null
```

Do not invent application IDs, hashes, timestamps, or asset IDs.

## motion_recommendation

Required for every beat.

Allowed `type` values:
- `static`
- `native`
- `slow_zoom_in`
- `slow_zoom_out`
- `pan_left`
- `pan_right`
- `pan_up`
- `pan_down`

Required:
- `type`
- `purpose`
- `target`

`target` may be null.

### Meaning

`static`
- Still image remains still.
- This is a deliberate treatment, not a failure to edit.

`native`
- Use the selected video clip's natural motion without added digital pan/zoom.
- Use for video in Phase 7B.

`slow_zoom_in`
- Very restrained digital move inward.

`slow_zoom_out`
- Very restrained digital move outward.

`pan_left`
- Viewer/camera moves left across the still, ending farther left.

`pan_right`
- Viewer/camera moves right across the still, ending farther right.

`pan_up`
- Viewer/camera moves upward across the still.

`pan_down`
- Viewer/camera moves downward across the still.

`target`
- Name the visual detail or region the motion is intended to emphasize when applicable.
- Use null for `static`, `native`, or when there is no useful specific target.

### Motion rules

Motion must be based on the **actual selected visual** shown in the storyboard.

For a still:
- static is acceptable;
- use motion only when it directs attention or meaningfully supports narration;
- do not move every still;
- do not crop away the important subject;
- do not create random motion for activity.

For video:
- use `native`;
- Phase 7B does not add digital pan/zoom to normal video clips.

Good reasons:
- draw attention toward a relevant doorway, window, object, or figure;
- increase unease through a restrained approach;
- reveal more context with a slow pull out;
- move across a still toward the narratively important area.

Bad reasons:
- "The image is static."
- "We have not zoomed recently."
- "Variety."
- "Retention requires movement."

Do not create cadence rules.

## transition_out_recommendation

Required as an object for every non-final beat.

Final beat uses null.

Allowed `type` values:
- `cut`
- `cross_dissolve`
- `dip_to_black`

Required:
- `type`
- `to_beat_id`
- `purpose`

`to_beat_id` must be the immediately following beat.

### Transition intent

`cut`
- clear or immediate narrative change;
- reveal/contradiction that benefits from directness;
- adjacent visuals where dissolve would feel muddy.

`cross_dissolve`
- calm continuity;
- gentle passage within a related section;
- atmospheric transition where softness helps narration.

`dip_to_black`
- meaningful break, time jump, section change, or strong separation;
- use sparingly.

### Transition rules

- Choose for narrative function, not variety.
- Do not alternate types mechanically.
- Do not use `dip_to_black` as routine punctuation.
- Do not add wipes, spins, zoom transitions, glitches, flashes, or unsupported effects.
- Repeated cuts are acceptable when appropriate.
- Repeated dissolves are acceptable when genuinely useful; do not vary merely to avoid repetition.

## Relationship to SFX

Edit Plan v1 does not recreate or overwrite Visual Plan SFX recommendations.

The storyboard may show selected SFX and it may inform judgment, but Edit Plan v1 carries only motion and transition recommendations in Phase 7B.

## Producer authority

The producer may:
- keep the recommendation;
- choose different motion;
- choose a different transition;
- return a still to static;
- leave video native;
- ignore a recommendation.

## Validation

Before outputting, verify:
- `document_type` is `edit_plan`;
- `contract_version` is `1`;
- story ID matches the storyboard;
- every storyboard beat appears exactly once;
- beat IDs and sequences match;
- every beat has a motion recommendation;
- motion type is valid;
- image beats do not use `native`;
- video beats use `native`;
- every non-final beat has one transition-out recommendation;
- each `to_beat_id` is the immediately following beat;
- final beat transition is null;
- only supported transition types are used;
- purposes are specific to actual selected media/narration;
- choices are restrained and not quota-driven.

## Example

```json
{
  "document_type": "edit_plan",
  "contract_version": 1,
  "story": {
    "story_id": "example-house-story"
  },
  "beats": [
    {
      "beat_id": "beat-001",
      "sequence": 1,
      "motion_recommendation": {
        "type": "static",
        "purpose": "The wide bedroom composition already establishes the ordinary setup; movement would add emphasis before the story earns it.",
        "target": null
      },
      "transition_out_recommendation": {
        "type": "cut",
        "to_beat_id": "beat-002",
        "purpose": "The first unmistakable movement should arrive directly rather than dissolve out of the calm setup."
      }
    },
    {
      "beat_id": "beat-002",
      "sequence": 2,
      "motion_recommendation": {
        "type": "slow_zoom_in",
        "purpose": "A restrained move toward the displaced chest increases attention after the reveal without creating a jump-scare effect.",
        "target": "chest of drawers"
      },
      "transition_out_recommendation": null
    }
  ]
}
```
