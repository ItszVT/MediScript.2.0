# Optional: enable a real medical NER model (Windows PowerShell).
# Not required — MediScript ships with an offline heuristic detector.
Write-Host "Installing spaCy + Med7 (en_core_med7_lg)..."
pip install --upgrade spacy
pip install "https://huggingface.co/kormilitzin/en_core_med7_lg/resolve/main/en_core_med7_lg-any-py3-none-any.whl"
Write-Host ""
Write-Host "Done. Add to your .env:"
Write-Host "  DRUG_NER_MODEL=en_core_med7_lg"
Write-Host "  DRUG_NER_LABELS=DRUG"
