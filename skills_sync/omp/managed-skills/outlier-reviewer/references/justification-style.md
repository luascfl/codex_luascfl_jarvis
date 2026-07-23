# Justification style

Use this reference when Lucas asks for a justification, feedback, screening answer, or final comparison.

## Lucas-style principles

- Start with the verdict.
- Name the criteria inside the justification, not only in notes.
- For each important criterion, make the status visible: met, partially met, or failed.
- Pair each criterion with evidence from the response.
- Explain the impact of each failed criterion on the final goal or score.
- Avoid subjective summary labels unless they are tied to a named criterion.
- Replace vague praise like "clear", "helpful", "good", or "useful" with the specific criterion that made it so, such as writing quality, structure, formatting, concision, source use, or task fit.
- Keep the language direct and natural.
- Avoid generic praise.
- Do not overexplain dimensions that do not affect the score.

Use this chain: **criterion → status → evidence → impact**.

Good justification writing should make the reader see exactly which criteria passed and which failed without needing a separate table. If a sentence says "clear" or "useful", it must also say the criterion and evidence, for example: "For writing quality, it met the structure criterion because it used organized bullets for performance, build quality, display, and battery."

## Independent justification checklist

Before delivering, verify:

1. It states how well the response met the final goal.
2. It names the main criteria inside the paragraph.
3. Each named criterion has a clear status: met, partially met, or failed.
4. It cites actual content from the response as evidence.
5. It includes a strength.
6. It includes a miss, limitation, or wrong choice.
7. It explains why the miss matters.
8. It does not compare to another model unless the field is a final comparison.
9. It matches the required language.
10. It fits the requested length.

## Preferred wording

Use:

- "The response only partially met the final goal because..."
- "For [criterion], it [passed/partially met/failed] because..."
- "This affects [dimension] because..."
- "The main failed criterion was..."
- "The strongest met criterion was..."

Avoid:

- "Good response."
- "Very helpful overall."
- "It met the goal well."
- "It was clear" without naming the criterion and evidence.
- "It was useful" without naming what user need or criterion it served.
- "Overall, it was clear but..." as a substitute for criterion-based evaluation.
- "The model was better than the other one" in individual feedback.
- Long introductions.

## Example, independent justification

Task: student asks for a couple of affordable laptop options for writing, browsing, and Zoom. Model recommends only a $1,599 MacBook Pro.

Weak pattern, avoid this:

```text
The response only partially met the final goal because it passed the basic-use criterion but failed the affordability and option-count criteria. For basic use, the 14-inch MacBook Pro with M3 would handle writing, browsing, and Zoom calls, and the response supported that with battery life, build quality, and performance details. For affordability, it failed because a laptop starting around $ 1,599 does not fit a college student on a really tight budget. For option count, it also failed because the user asked for a couple of options, but the response recommended only one laptop. Overall, the response was clear and factually plausible, but the failed budget and multiple-option criteria create major instruction-following issues.
```

Why it is weak: the word "clear" is subjective and not tied to a criterion. If clarity matters, name the exact criterion, usually writing quality, structure, formatting, or readability.

Preferred criterion-forward pattern:

```text
The response only partially met the final goal because it passed the basic-use criterion but failed the affordability, option-count, and casual-user-fit criteria. For basic use, the 14-inch MacBook Pro with M3 would handle writing, browsing, and Zoom calls, so that criterion was met. For writing quality, it partially met the structure criterion because it organized the recommendation into bullets about performance, build quality, display, and battery. For affordability, it failed because a laptop starting around $ 1,599 does not fit a college student on a really tight budget. For option count, it failed because the user asked for a couple of options, but the response recommended only one laptop. For casual-user fit, it also missed because premium technical details like the M3 chip and Liquid Retina XDR display do not match a user who only needs a simple school laptop.
```

This is better because every positive and negative claim names the criterion, status, and evidence. It avoids subjective labels like "clear" unless they are converted into a specific criterion such as writing quality or structure.

## Model-specific feedback template

```text
The model [fully/mostly/partially] reached the final goal because it [passed/failed] [main criteria]. For [met criterion], it [status] because [evidence]. For [failed criterion], it [status] because [evidence]. This affected [dimension/score/user need] because [impact]. Overall, [score-aligned conclusion using criteria, not subjective praise].
```

## Final comparison template

```text
I prefer [Model A/B] because it better satisfied [main user need] through [specific evidence]. Model A [specific strength/weakness], while Model B [specific strength/weakness]. The biggest difference was [dimension], especially [example]. Although [other model] did [strength], it fell short on [specific miss]. This makes [winner] the stronger choice overall because [score-aligned conclusion].
```

## Dimension phrasing

- Instruction Following: "For [constraint], the response failed because..."
- Truthfulness: "For factual accuracy, the response failed because..."
- Writing Quality: "For structure/readability/formatting, the response met or partially met the criterion because..."
- Localization: "For localization, the recommendation failed because..."
- Verbosity: "For concision, the answer failed or partially met the criterion because..."
- Satisfaction: "For user fit, the response fell short because the user would still need to..."

## Center Circle reminder

- Individual feedback: no comparison.
- Final justification: comparison required.
- 4 to 6 sentences unless the current task says otherwise.
- English final text.
- If required, include thin space ` `.
