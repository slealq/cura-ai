"""Prompt templates shared by the fal vision/language providers."""

CLUSTER_SUMMARY_PROMPT = """You're summarizing a cluster of {size} similar images.

Common tags in this cluster:
{tags}

Sample descriptions from images in this cluster:
{descriptions}

Create:
1. **summary_title**: A concise title (3-7 words) capturing the essence of this group.

2. **summary_description**: 2-4 bullet points describing the unifying visual style, common elements, and what makes this group distinctive.

Return ONLY a valid JSON object (no other text):
{{
  "summary_title": "...",
  "summary_description": "- bullet 1\\n- bullet 2\\n..."
}}"""



EVAL_PROMPT = """You are a STRICT evaluator assessing how well a LoRA-trained model reproduced a reference image.

You are given:
1. The ORIGINAL reference image (first image)
2. The GENERATED image from a LoRA model (second image)
3. The prompt used to generate the image

**Prompt used:** {prompt}

## Scoring Calibration (FOLLOW STRICTLY)

Score each dimension from 0 to 10 using these anchors:
- **0-1**: Completely different. No recognizable connection between the images.
- **2-3**: Vaguely similar concept only. Different subject, different style, different composition.
- **4-5**: Same general subject or concept but clearly different execution. Noticeable style, color, or composition differences. Most details don't match.
- **6**: Recognizably attempting the same scene but with significant differences. Multiple wrong details.
- **7**: Same scene and style with some visible differences in details, proportions, or textures.
- **8**: Very close match with only minor differences noticeable on careful inspection.
- **9**: Nearly identical. Only subtle pixel-level differences.
- **10**: Indistinguishable. Reserve ONLY for perfect reproductions.

Most LoRA-generated images should score between 3 and 7. Scores above 8 should be exceptionally rare.

## CRITICAL: Human Features Penalty

If the images contain human faces, bodies, or anatomy:
- ANY distortion in facial features (wrong proportions, asymmetry, extra/missing features) → subject_accuracy MUST be ≤ 4
- Different person identity (wrong face, different person) → subject_accuracy MUST be ≤ 3
- Anatomical errors (wrong number of fingers, distorted limbs, impossible poses) → detail_preservation MUST be ≤ 3
- Uncanny valley effects → overall MUST be penalized by at least 2 points

## Dimensions

- **style_fidelity**: Does the generated image match the visual style? Same color palette, lighting, artistic technique, mood, and rendering quality?
- **subject_accuracy**: Does it capture the EXACT same subject? Same person/object identity, composition, pose, and spatial arrangement? Not just "similar looking" — the SAME subject.
- **detail_preservation**: Are fine details correct? Textures, patterns, text, small objects, backgrounds, accessories. Every missing or wrong detail reduces this score.
- **overall**: Holistic assessment. This MUST NOT be higher than the lowest dimension score + 2. If any dimension is ≤ 3, overall CANNOT exceed 5.

## Assessment

Provide a 2-3 sentence assessment focused on what went WRONG. What specific details differ? What features are missing or distorted? Be critical, not generous.

Return ONLY a valid JSON object (no other text):
{{
  "style_fidelity": <number>,
  "subject_accuracy": <number>,
  "detail_preservation": <number>,
  "overall": <number>,
  "assessment": "<string>"
}}"""


CREATIVE_EVAL_PROMPT = """You are a STRICT image quality evaluator assessing a single generated image from a LoRA-trained model.

There is NO reference image. You are evaluating this image purely on its own quality and fidelity to the prompt.

**Prompt used to generate:** {prompt}

## Scoring Calibration (FOLLOW STRICTLY)

Score each dimension from 0 to 10:
- **0-1**: Completely broken. Unrecognizable or incoherent.
- **2-3**: Major quality issues. Significant artifacts, distortion, or incoherence.
- **4-5**: Below average. Multiple noticeable problems with realism or detail.
- **6**: Acceptable but clearly AI-generated. Some artifacts or unrealistic elements.
- **7**: Good quality with minor issues. Mostly realistic with a few tells.
- **8**: High quality. Very few artifacts, realistic details.
- **9**: Excellent. Nearly flawless quality.
- **10**: Perfect. Reserve ONLY for exceptional quality.

## CRITICAL: Realism and Anatomy

- ANY facial distortion, asymmetry, or uncanny valley = realism MUST be ≤ 4
- Wrong number of fingers, distorted limbs, impossible anatomy = detail_quality MUST be ≤ 3
- Garbled or nonsensical text/lettering = detail_quality penalty of at least -2
- Repetitive patterns, texture glitches, or melted/blurred areas = realism penalty

## Dimensions

- **realism**: How realistic and natural does the image look? Free from AI artifacts, distortions, uncanny valley effects?
- **prompt_adherence**: How well does the image match what was described? Are all described elements present and correct?
- **detail_quality**: Quality of fine details — textures, edges, small objects, backgrounds. Crisp and accurate or blurry/malformed?
- **overall**: Holistic quality. MUST NOT be higher than the lowest dimension score + 2.

## Assessment

Provide a 2-3 sentence assessment focused on issues. What artifacts? What's missing from the prompt? What looks unnatural? Be critical and harsh.

Return ONLY a valid JSON object (no other text):
{{
  "realism": <number>,
  "prompt_adherence": <number>,
  "detail_quality": <number>,
  "overall": <number>,
  "assessment": "<string>"
}}"""


ASSESSMENT_SUMMARY_PROMPT = """You are summarizing the results of a LoRA model evaluation.

The LoRA model "{model_name}" (trigger word: "{trigger_word}") was evaluated by generating images and comparing them against originals from the training set.

{creative_section}

## Individual Pair Assessments

{pair_assessments}

## Aggregate Scores
- Overall Score: {overall_score}
- Average Vision Score: {avg_vision}
- Average Embedding Similarity: {avg_embedding}

## Your Task

Write a concise 3-5 sentence evaluation summary that:
1. States the overall quality verdict (poor / below average / acceptable / good / excellent)
2. Identifies the MAIN patterns of failure — what consistently goes wrong?
3. Highlights any strengths if they exist
4. Gives a specific, actionable recommendation (e.g., "increase training steps", "reduce learning rate", "add more diverse training images")

Focus on patterns and what went wrong, not on restating individual scores. Be direct and critical.

Return ONLY a valid JSON object (no other text):
{{
  "summary": "<string>"
}}"""


CREATIVE_PROMPT_GENERATION = """You are generating creative image prompts for testing a LoRA model's generalization ability.

The LoRA model was trained with trigger word "{trigger_word}" on images described as:

{sample_descriptions}

Generate {count} new, creative prompts that:
1. MUST start with the trigger word "{trigger_word}"
2. Are INSPIRED by the training set but describe ENTIRELY NEW scenes, compositions, or scenarios not present in the originals
3. Test the model's ability to generalize beyond its training data
4. Cover different scenarios, environments, lighting conditions, or styles
5. Are detailed enough to produce specific images (2-3 sentences each)

Return ONLY a valid JSON object (no other text):
{{
  "prompts": ["<prompt1>", "<prompt2>", ...]
}}"""


