# Prompt types and constraints

Condensed from Lucas's manual CSV files.

## Prompt types

| Type | Use when | Common checks |
|---|---|---|
| Open QA | The answer comes from general knowledge, not a supplied text. | Accuracy, completeness, practical usefulness, constraints. |
| Closed QA | The answer must be based on provided text. | Source fidelity, no unsupported facts, direct answer. |
| Classification | The model must group, label, sort, or choose categories. | Correct categories, rule adherence, no missing items. |
| Retrieval | The prompt asks for information from named sources or broader reference material. | Correct source use, citations if requested, no fabrication. |
| Extraction | The model must pull specific information from text. | Exactness, completeness, no paraphrase if quotes are required. |
| Modification/Rewrite | The model must change style, tone, voice, POV, grammar, or format. | Meaning preserved, target style achieved, constraints followed. |
| Summarization | The model must shorten a text to key ideas. | Coverage, concision, length, requested focus. |
| Brainstorming | The model must generate options or ideas. | Quantity, relevance, creativity, constraints. |
| Chatbot | The model must speak as a role, persona, or character. | Persona consistency, usefulness, instruction following. |
| Creative Writing | The model must produce imaginative writing. | Creativity, format, tone, prompt constraints. |

## Constraint categories

### Information inclusion/exclusion

Examples:
- Include X.
- Exclude Y.
- Only focus on Z.
- Provide a list that satisfies multiple content filters.

Evaluation note: missing an inclusion or violating an exclusion is usually Instruction Following.

### POV, tone, audience, dialect

Examples:
- Formal or informal tone.
- Write for a 10-year-old.
- Rewrite from a specific character/person’s perspective.
- Use a local dialect instead of a standard variety.

Evaluation note: wrong tone can be Writing Quality or Instruction Following depending on how explicit the prompt was.

### Formatting

Examples:
- Bullet points.
- Numbered list.
- Table.
- Bold specific words.
- Chronological or descending order.
- Dates in a given format.

Evaluation note: if the prompt explicitly required it, wrong format is Instruction Following. If format only affects readability, it is Writing Quality.

### Location

Examples:
- Local restaurants, addresses, landmarks.
- Within a distance from a location.
- Specific city, country, dialect, or region.

Evaluation note: wrong geography can affect Localization and Truthfulness.

### Seasonal or date-specific

Examples:
- Events on a specific date.
- Activities only available in a certain season.

Evaluation note: check factuality and timeliness.

### Summarization

Examples:
- Summarize in exactly 3 lines.
- Summarize but focus only on X.
- Use bullets or bold keywords.

Evaluation note: judge both coverage and compression.

### Rewrite

Examples:
- Rewrite in active voice.
- Rewrite as an announcement.
- Rewrite from a fan’s perspective.
- Explain technical terms in parentheses.

Evaluation note: preserve meaning unless the task explicitly asks to transform content.

### Classification

Examples:
- Categorize food items.
- Sort events chronologically.
- Classify by genetic/non-genetic causes.

Evaluation note: check every item. One missing or miscategorized item matters.

### Closed QA

Examples:
- Answer based on an article.
- Identify symptoms from a provided list.
- Use technical terms from the source.

Evaluation note: source-bound tasks punish unsupported additions.

### Brainstorming

Examples:
- Generate names.
- Suggest restaurants with pet-friendly outdoor space.
- Give ideas for interactive fiction.

Evaluation note: quality depends on satisfying constraints, not just creativity.

### Open QA

Examples:
- Explain a concept from general knowledge.
- Give advantages and disadvantages.
- Recommend options.

Evaluation note: check factual accuracy and whether the options fit the user’s real constraints.
