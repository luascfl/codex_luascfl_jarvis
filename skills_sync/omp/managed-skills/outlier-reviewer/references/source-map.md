# Source map

This skill was drafted from Lucas's manual Outlier structure files in `/home/lucas/Downloads/outlier/`.

## Source files

- `Estrutura Outlier.md`
  - Provides the evaluation skeleton:
    - main idea of prompt in one sentence;
    - objective and constraints;
    - response A and B;
    - Instruction Following;
    - Writing Quality;
    - Truthfulness;
    - truthfulness research note;
    - Justification.

- `Estrutura Outlier.xlsx - Prompt Making.csv`
  - Provides the spreadsheet columns for evaluating Model A and Model B:
    - Prompt type;
    - Prompt;
    - Objective and constraints;
    - Response A and Response B;
    - Localization;
    - Instruction Following;
    - Truthfulness;
    - Category-specific checks;
    - Verbosity;
    - Writing Quality;
    - Harmlessness;
    - Overall Score;
    - Justification.

- `Estrutura Outlier.xlsx - Prompt Making #2.csv`
  - Provides default no-issue evaluation states and the Portuguese summary labels:
    - `Perfeita` when all dimensions have no issues.

- `Estrutura Outlier.xlsx - Constraints.csv`
  - Provides constraint categories and examples:
    - Information inclusion/exclusion;
    - POV/tone;
    - Formatting;
    - Location;
    - Seasonal/date-specific;
    - Summarization;
    - Rewrite;
    - Classification;
    - Closed QA;
    - Brainstorming;
    - Open QA.

- `Estrutura Outlier.xlsx - Prompt Types.csv`
  - Provides prompt type definitions:
    - Open QA;
    - Closed QA;
    - Classification;
    - Retrieval;
    - Extraction;
    - Modification/Rewrite;
    - Summarization;
    - Brainstorming;
    - Chatbot;
    - Creative Writing.

## Related project material

- `/home/lucas/Downloads/outlier/mapa-boas-praticas-justificativas.md`
  - Maps related Outlier documents about good justifications.

- `/home/lucas/Downloads/outlier/center circle/AGENTS.md`
  - Center Circle project rules.

- `/home/lucas/Downloads/outlier/center circle/instrucoes-outlier.md`
  - Portuguese consolidation of Center Circle instructions.

## Skill design decision

The skill should not mechanically fill every spreadsheet column every time. It should first infer the task type, then use only the dimensions that affect the judgment. This keeps the output close to Lucas's writing style: concise, concrete, score-aligned, and not overexplained.
