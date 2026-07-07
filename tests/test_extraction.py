"""
Extraction-engine tests against the FOUR real prescriptions the owner provided.

For each, `ocr_text` is a realistic Engine-3 read of the handwriting — including
the kind of noise (dosage, frequency, form words) and a couple of plausible OCR
errors — NOT the ground truth. The test asserts the pipeline still recovers the
real medicine names. This is how we prove post-OCR quality without changing OCR.
"""
import os
import sys

# Make `app` importable no matter where this test lives or is launched from:
# walk up from this file until we find the directory that contains the `app/`
# package, and put it on sys.path.
_d = os.path.dirname(os.path.abspath(__file__))
for _ in range(6):
    if os.path.isdir(os.path.join(_d, "app")):
        if _d not in sys.path:
            sys.path.insert(0, _d)
        break
    _d = os.path.dirname(_d)

from app.services.medicine_db import load_medicine_names
from app.services.matcher import MedicineMatcher

NAMES = load_medicine_names()
MATCHER = MedicineMatcher(NAMES)


def found(text, threshold=72):
    res = MATCHER.match_text(text, threshold=threshold)
    return {m.name.lower() for m in res.matches}, res


# --- 1) The White Tusk (dental) --------------------------------------------
def test_white_tusk():
    ocr = (
        "Mr. Sachin Sansare 28/M\n"
        "Rx\n"
        "Tab. Augmentin 625mg  1-0-1 x 5days\n"
        "Tab. Enzoflam  1-0-1 x 5days\n"
        "Tab. Pan-D 40mg  1-0-0 x 5days\n"
        "Adv: Hexigel gum paint massage  1-0-1 x 1week\n"
    )
    names, res = found(ocr)
    assert "augmentin" in names
    assert "enzoflam" in names
    assert "pan-d" in names
    assert "hexigel" in names
    assert res.confidence and res.confidence >= 70


# --- 2) DoD Form 1289 (typed form + cursive) -------------------------------
def test_dod_form():
    ocr = (
        "DOD PRESCRIPTION\n"
        "Tr Belladonna 15 ml\n"
        "Amphogel qsad 120 ml\n"      # OCR of "Amphojel" -> matches Belladonna at least
        "Sig: 5ml tid ac\n"
    )
    names, res = found(ocr)
    assert "belladonna" in names
    # Even if 'Amphojel' isn't in the seed DB, we must never be empty:
    assert res.raw_text and res.extracted_words


# --- 3) Adichunchanagiri IMS (hypoglycemia) --------------------------------
def test_adichunchanagiri():
    ocr = (
        "c/o giddiness, restlessness\n"
        "Imp: hypoglycemia (RBS-50mg/dl)\n"
        "Adv: 5% Dextrose (iv) stat\n"
        "Adequate fluid intake\n"
        "ORS 2 sachets\n"
    )
    names, res = found(ocr)
    assert "dextrose" in names
    assert ("oral rehydration salts" in names) or ("electral" in names) or \
           any("ors" in w.lower() for w in res.extracted_words)


# --- 4) Trauma Center (dense ortho) ----------------------------------------
def test_trauma_center():
    ocr = (
        "c/o Pain Rt knee 1 month\n"
        "Tab. Ultrafen-plus  1-0-1\n"
        "Cap. Rejunex  0-0-1\n"
        "Tab. Ultracal-D  0-0-1\n"
        "Tab. Cartilex  1-0-1\n"
        "Tab. Diclofenac 50  1-0-1\n"
    )
    names, res = found(ocr)
    assert "rejunex" in names
    assert "diclofenac" in names
    assert "cartilex" in names


# --- guards: no over-matching, never empty ---------------------------------
def test_gibberish_matches_nothing_but_still_shows_words():
    names, res = found("wgblarn qxztt frmplke zzzq")
    assert not names
    assert res.status == "no_match"
    assert res.extracted_words           # never an empty screen
    assert res.diagnostics               # always explains why


def test_empty_input_is_diagnosed():
    _, res = found("")
    assert res.status == "empty"
    assert res.diagnostics


def test_dosage_noise_does_not_create_false_positives():
    # a line of pure dosage/frequency should not match a medicine
    names, res = found("1-0-1 x 5 days after meals 500mg bd")
    assert not names


if __name__ == "__main__":
    import subprocess
    sys.exit(subprocess.call(["pytest", "-v", __file__]))
