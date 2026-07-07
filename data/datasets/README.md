# Add your own medicine datasets here

Drop any number of `.csv` or `.txt` files into this folder and run:

    python scripts/build_medicine_db.py

Every file here is auto-discovered and merged into the search index — no code
changes needed. Use as many datasets as you like; they're combined and
de-duplicated.

## Format

- **CSV**: any column whose header contains `name`, `medicine`, `drug`,
  `brand`, `product`, or `composition` is used. Other columns are ignored.
  Example:
      name,manufacturer
      Dolo 650 Tablet,Micro Labs
      Crocin Advance,GSK
- **TXT**: one medicine name per line.

## Where to get good datasets (real, not fabricated)

- Kaggle — "A-Z Medicines Dataset of India" (250k+ Indian brands + compositions)
- Kaggle — "Extensive A-Z Medicines Dataset of India" (adds uses/side effects)
- Kaggle — "India Medicines and Drug Info Dataset" (Tata 1mg export)
- WHO Model List of Essential Medicines (generic names)
- Open BNF (already bundled)

Download the CSV, drop it here, rebuild. Brand product names are cleaned
automatically (dosage/pack/form suffixes stripped) so they match well.

Files in this folder are git-ignored by default (they can be large) — commit
them explicitly if you want them in your repo.
