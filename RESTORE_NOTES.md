# FZAstro AI Restore Package

This package is the clean current source baseline prepared after the working FZAstro Imaging/N.I.N.A. integration.

Included:
- main.py
- fzastro_ai/
- scripts/
- tests/
- docs/
- requirements.txt
- FZAstroAI.spec
- README.md

Intentionally not included because they are large/generated/local:
- external/
- bundled_apps/
- build/
- dist/
- D:\Dropbox\FZAstroAI_BUILD\

Current imaging state:
- FZAstro Imaging/N.I.N.A. uses internal NINA.exe and NINA.dll.
- FZAstroImaging.exe is a branded copied launcher name only.
- Imaging plans are saved under Documents\FZAstroAI\Imaging Plans.
- The generated .nina-sequence.json is the file to open/import in N.I.N.A. Advanced Sequencer.
- Hardware actions remain review-only unless explicitly implemented later.

Suggested validation after restoring:

```powershell
cd D:\Dropbox\AI
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m compileall -q .\main.py .\fzastro_ai .\tests
```
