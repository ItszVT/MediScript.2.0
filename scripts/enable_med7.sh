#!/usr/bin/env bash
# Optional: enable a real medical NER model for medicine detection.
# This is NOT required — MediScript ships with an offline heuristic detector.
# Only run this if you want model-based DRUG entity recognition and have the
# disk/RAM for it (~500MB–1GB). Needs network access to download the model.
set -e

echo "Installing spaCy + Med7 (en_core_med7_lg)…"
pip install --upgrade spacy
# Med7 large (CNN) — label: DRUG
pip install "https://huggingface.co/kormilitzin/en_core_med7_lg/resolve/main/en_core_med7_lg-any-py3-none-any.whl"

echo
echo "Done. Now set these in your .env (or environment):"
echo "  DRUG_NER_MODEL=en_core_med7_lg"
echo "  DRUG_NER_LABELS=DRUG"
echo
echo "Alternative (scispaCy, label CHEMICAL):"
echo "  pip install scispacy"
echo "  pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz"
echo "  DRUG_NER_MODEL=en_ner_bc5cdr_md   DRUG_NER_LABELS=CHEMICAL"
