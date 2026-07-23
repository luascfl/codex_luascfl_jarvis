---
name: calculate-speech-time
description: "How to calculate speech time (Locução Rápido) based on textconverter.io using the 155 WPM constant. (User preference: ALWAYS use Locução Rápido)."
---

## Origem
Criada a partir do contexto: `Global`

# Calculation of Speech Time (textconverter.io methodology)

This skill replicates the speech time calculation logic found on textconverter.io, specifically for voiceovers and speeches.

## User preference

The user, Lucas, has explicitly requested to always use the `Locução` mode set to `Rápido` as the default for all calculations.

Therefore, always default to `155 WPM` when calculating reading or video script times for him, unless he specifically asks for another speed.

## The Formula

The site uses a simple Words Per Minute (WPM) division to estimate reading time.

1. Count the total words in the text.
2. Divide the total words by `155` (`Locução Rápido`).
3. The integer part of the result represents the minutes.
4. The fractional part multiplied by 60 represents the seconds, floored.

## Other WPM Rates by Mode (For Reference Only)

- `Locução` (Voiceover)
  - Normal: 135 WPM
  - Rápido: 155 WPM, default
- `Discurso` (Speech)
  - Normal: 90 WPM
  - Rápido: 110 WPM

## Python Implementation Example

```python
import math

def calculate_speech_time(text, wpm=155):
    words = len(text.split())
    total_minutes = words / wpm
    minutes = math.floor(total_minutes)
    seconds = math.floor((total_minutes - minutes) * 60)
    return f"{minutes}min {seconds}sec"

text = "palavra " * 1001
print(calculate_speech_time(text))
# Output: 6min 27sec
```
