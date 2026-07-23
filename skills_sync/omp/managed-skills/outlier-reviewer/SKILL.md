---
name: outlier-reviewer
description: Use this skill whenever Lucas asks for help with Outlier reviewer tasks, AI response evaluation, identifying prompt type, extracting objective and constraints, rating criteria, writing justifications in Lucas's concise style, comparing Model A vs Model B, Center Circle screening, RLHF/SxS reviews, preference ranking, or checking whether feedback matches scores. This skill should trigger even when the user only pastes a task screenshot or says "me ajuda nessa task", "qual prompt type", "faz a justification", "avalia A e B", or "quais critérios".
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/outlier`


# Outlier reviewer

This skill helps Lucas solve Outlier reviewer tasks using his own manual structure: identify prompt type, extract objective and constraints, evaluate responses by dimensions, and write concise evidence-based justifications.

Use it for Outlier projects, Center Circle, RLHF/SxS comparisons, screening quizzes, prompt classification, constraints extraction, rating alignment, feedback and justification writing.

## Core workflow

When Lucas provides a task, do this in order:

1. Identify the task format.
   - Single model independent justification.
   - Model A vs Model B comparison.
   - Prompt type classification.
   - Rubric or dimension rating.
   - Criteria/constraints extraction.
   - Feedback review before submission.

2. Extract the prompt skeleton.
   - Main idea in one sentence.
   - Objective `(0)`.
   - Constraints `(1, 2, 3...)`.
   - Prompt type.
   - Whether the answer must rely on provided reference text.
   - Any hidden user priority, like budget, exact format, safety, language, location, or audience.

3. Evaluate each response against the objective and constraints.
   - Do not start with preference. Start with requirement matching.
   - Separate errors by dimension: Instruction Following, Writing Quality, Truthfulness, Localization, Verbosity, Harmlessness, Category-specific checks.
   - Mention only dimensions that matter for the task. Do not overfill.

4. Write the justification in Lucas's style.
   - Direct first sentence: how well the response met the goal.
   - Concrete evidence from the response.
   - One real strength.
   - One real miss, weakness, or limitation.
   - Score/preference implication if relevant.
   - No filler and no generic praise.

5. Check submission rules.
   - If individual feedback: do not compare models.
   - If final justification: compare models with concrete differences.
   - If Center Circle: final text must be in English and usually 4 to 6 sentences.
   - If the platform requires a special character, such as a thin space, include it intentionally and point it out.

6. Preserve Lucas's authorship style when he sends his own justifications.
   - If Lucas says or implies that a justification was written by him, append it to `/home/lucas/Downloads/outlier/Estrutura Outlier.md`.
   - Use the `Histórico de justificativas autorais` section.
   - Do not rewrite the original justification before saving it.
   - Add short metadata when available: date, project/task, prompt type, objective, main criteria.
   - Add 2 to 4 style notes about how Lucas specified criteria, failures, evidence, tone, or conclusion.
   - If metadata is missing, leave the metadata field blank rather than inventing it.
   - If Lucas's justification is partial or unfinished, keep his exact words as the opening and continue from there.
   - Do not replace, polish, translate, or reorder Lucas's existing sentence unless he explicitly asks for a rewrite.
   - Add only what is missing for the task: required length, concrete evidence, passed/failed criteria, balanced strength/weakness, score impact, thin space, or final conclusion.
   - Before continuing a partial justification, briefly explain what Lucas already filled in and what remains missing.
   - Use this diagnostic format:
     - `Preenchido:` list the filled parts, such as verdict, failed criterion, evidence, impact, strength, weakness, score implication, required language, or special character.
     - `Falta:` list only missing parts needed by the current task, such as concrete evidence, named met criterion, named failed criterion, impact, balanced positive point, 4-6 sentence length, thin space, or final score-aligned conclusion.
     - `Continuação:` continue from Lucas's exact text without changing it.
   - If his sentence has grammar issues but is understandable, preserve it and continue naturally after it.
   - If the platform requires English and Lucas started in English, continue in English. If he started in Portuguese but the platform requires English, ask whether he wants translation or provide a separate translated final version without overwriting the original.

## Authorship history append format

When appending Lucas's own justification to `/home/lucas/Downloads/outlier/Estrutura Outlier.md`, use:

```md
### YYYY-MM-DD — [project/task if known]

Contexto:
- Prompt type: [if known]
- Objetivo: [if known]
- Critérios principais: [if known]

Justificativa original de Lucas:
> [exact text Lucas wrote]

Notas de estilo observadas:
- [specific observation]
- [specific observation]
```

This history is not a dataset of perfect answers. It is a style memory. Preserve wording that shows Lucas's authorship, even when later suggesting an improved version separately.

## Prompt skeleton template

Use this scratch structure internally or show it when Lucas asks for analysis:

```md
Main idea: [one sentence]

Objective (0): [what the model must accomplish]
Constraints:
1. [explicit constraint]
2. [explicit constraint]
3. [implicit but necessary constraint, if supported by task]

Prompt type: [Open QA / Closed QA / Classification / Extraction / Rewrite / Summarization / Brainstorming / Chatbot / Creative Writing / Retrieval]
Reference text required: yes/no
Likely failure modes: [hallucination, missed constraint, wrong format, overlong, unsafe, not localized, etc.]
```

## Prompt type guide

Use these definitions from Lucas's manual files.

- Open QA: answer from general knowledge, not a specific provided text.
- Closed QA: answer must come from provided text. The model should not invent beyond the reference.
- Classification: put items into categories or decide labels based on rules.
- Extraction: pull specific information from a provided text without transforming the whole text.
- Modification/Rewrite: change wording, tone, POV, format, or style while preserving meaning.
- Summarization: compress a longer text into its key ideas.
- Brainstorming: generate ideas or suggestions. Usually no single factual answer.
- Chatbot: adopt a role, persona, character, or perspective in an interaction.
- Creative Writing: produce imaginative or literary content.
- Retrieval: pull or synthesize information from named external sources or a broader knowledge set.

Decision shortcuts:

- If the task says "based on the following text/article/document", default to Closed QA, Extraction, Summarization, Classification, or Rewrite depending on the action.
- If it asks for exact quotes, dates, names, body parts, lists from a source, it is Extraction.
- If it asks to group, label, sort into categories, or choose between labels, it is Classification.
- If it asks to make shorter, it is Summarization.
- If it asks to change tone, voice, audience, style, POV, format, or grammar, it is Rewrite.
- If it asks for recommendations or facts without reference text, it is Open QA or Brainstorming. Use Brainstorming when creativity or options matter more than factual retrieval.

## Constraint categories

When extracting constraints, use these labels when helpful:

- Information inclusion/exclusion: include X, exclude Y, only focus on Z.
- POV/tone/audience: formal, casual, teacher POV, local dialect, child-friendly, expert-facing.
- Formatting: bullet points, numbered list, table, bold terms, order, dates in a format.
- Location: geography, local places, addresses, distance, local dialect, regional availability.
- Seasonal/date-specific: only things available in a season or tied to a date/event.
- Summarization constraints: length, focus, style, exact number of lines or bullets.
- Rewrite constraints: preserve meaning while changing style, audience, voice, or format.
- Classification constraints: categories, exclusion rules, chronological sorting, definitions.
- Closed QA constraints: answer only from source, use technical terms, avoid unsupported advice.
- Brainstorming constraints: number of ideas, theme, location, budget, audience, novelty.
- Open QA constraints: structure, length, ordering, external facts, practical usefulness.

Treat the user’s real need as a criterion when it is explicit. Example: "really tight budget" is not background color, it is a core constraint.

## Dimension evaluation guide

### Instruction following

Ask: did the response satisfy the objective and constraints?

Look for:
- Missing requested count, format, language, tone, audience, source basis, or budget.
- Answering a related but easier question.
- Giving one option when the user asked for a couple.
- Ignoring an exclusion or inclusion rule.

### Writing quality

Ask: is the response clear, usable, organized, and appropriate?

Look for:
- Clear structure and readable wording.
- Useful prioritization.
- No vague filler.
- Natural tone for the user.
- Good formatting when formatting matters.

### Truthfulness

Ask: are factual claims accurate and supportable?

Look for:
- Unsupported or invented facts.
- Wrong locations, prices, names, dates, availability, medical/legal claims.
- Claims not present in reference text for Closed QA or Extraction.

### Localization

Ask: does it fit the requested region, dialect, culture, units, currency, and local context?

Look for:
- Wrong country or city assumptions.
- Non-local recommendations.
- Mismatched dialect or spelling convention.

### Verbosity

Ask: is it the right length for the task?

Look for:
- Too much explanation for a simple ask.
- Missing detail when the task needs evidence.
- Repetition.

### Harmlessness

Ask: is it safe, respectful, and non-harmful?

Look for:
- Medical, legal, safety, self-harm, illegal, hate, privacy, or dangerous advice issues.

### Overall score / preference

Anchor preference in concrete differences, not vibes.

High-impact dimensions usually outweigh style:
- Instruction Following
- Truthfulness
- Harmlessness

Medium or lower impact unless severe or explicitly requested:
- Writing style
- Verbosity
- Formatting

## Lucas-style justification patterns

Lucas’s preferred justification is direct, specific, and evidence-first. It should sound like a reviewer, not a marketing blurb.

### Independent justification, single model

Use 4 to 6 sentences when the task asks for screening or Center Circle style.

Template:

```text
The response [fully/mostly/partially/barely/did not] met the final goal because [main reason tied to objective]. It [specific strength from the response]. However, it [specific miss tied to objective or constraint]. This matters because [why the miss affects usefulness or rating]. Overall, [final balanced assessment].
```

### Model-specific feedback, no comparison

Use this when writing Model A Feedback or Model B Feedback.

```text
The model [fully/mostly/partially] reached the final goal by [specific behavior]. It did well on [specific evidence], especially [detail]. It also handled [follow-up/format/constraint] by [detail]. The main weakness was [specific issue], which affected [dimension or user need]. Overall, the response was [usable/limited/strong] because [score-aligned conclusion].
```

Do not say "better than Model B" or "worse than Model A" here.

### Final comparative justification

Use this only in the final comparison field.

```text
I prefer [Model A/B] because it better satisfied [main user need] through [specific evidence]. Model A [specific strength/weakness], while Model B [specific strength/weakness]. The biggest difference was [concrete dimension], especially [example]. Although [other model] did [valid strength], it fell short on [specific miss]. This makes [winner] the stronger choice overall because [score-aligned conclusion].
```

### Rating-alignment sentence bank

Use these to tie text to score:

- "This is an instruction-following issue because the response missed [constraint]."
- "This affects truthfulness because [claim] is unsupported or inaccurate."
- "This affects satisfaction because the user would still need to [extra work]."
- "This is mostly a writing-quality issue, not a factual one, because [reason]."
- "The answer is useful, but the missing [constraint] keeps it from fully meeting the goal."

## Anti-patterns

Avoid these unless quoting the platform:

- "Good response" without evidence.
- "Very helpful overall" without naming why.
- "Met the goal well" without explaining what goal and what content met it.
- Comparing A and B inside individual feedback.
- Inventing a criterion not present in the task or project materials.
- Treating a premium, broad, or generic answer as good when the user asked for budget, local, short, source-based, or constrained output.
- Explaining every dimension when only one or two dimensions actually matter.

## Center Circle rules

For Center Circle specifically:

- First follow-up must come from `Considerations for Next Steps`.
- Treat both models with comparable patience.
- Max 10 turns.
- Stop when the final goal is satisfied, not before and not after.
- Individual feedback is independent, 4 to 6 sentences, no comparison.
- Final Justification is the only comparison field.
- Feedback and final justification must be in English.
- Mention turn behavior when relevant.
- Scores must match written feedback.

## Thin space handling

If the platform says the answer is incomplete without a thin space, include a real thin space character: ` `.

Safe placement:
- In a price: `$ 1,599`
- Between number and unit: `4 GB`

Tell Lucas where it is if useful, so he knows it was intentional.

## Source references bundled with this skill

Read these references only when needed:

- `references/source-map.md`: what each manual source contributed to the skill.
- `references/prompt-types-and-constraints.md`: condensed definitions and examples from Lucas’s CSV files.
- `references/justification-style.md`: writing templates and checklist.
