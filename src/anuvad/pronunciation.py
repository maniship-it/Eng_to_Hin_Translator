"""Turn CMU Pronouncing Dictionary entries into things a reader can use.

The CMU dictionary gives pronunciations in ARPAbet with stress digits::

    government  G AH1 V ER0 M AH0 N T

That is precise but unreadable. This module converts it into two forms that
help an actual user:

* **IPA** — ``/ˈɡʌv.ɚ.mənt/``, for anyone who reads dictionaries.
* **Respelling** — ``GUV-ur-muhnt``, for everyone else.

Both need the phones grouped into syllables, which ARPAbet does not mark, so a
maximal-onset syllabifier is applied first. It is a heuristic: it agrees with
dictionaries on ordinary words and can differ on unusual clusters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

#: ARPAbet vowels; every syllable is built around exactly one of them.
VOWELS = {
    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER",
    "EY", "IH", "IY", "OW", "OY", "UH", "UW",
}

_ARPABET_TO_IPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ",
    "EH": "ɛ", "ER": "ɝ", "EY": "eɪ", "IH": "ɪ", "IY": "i", "OW": "oʊ",
    "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ",
    "HH": "h", "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n",
    "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ", "T": "t",
    "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}

#: Unstressed AH and ER reduce to schwa in IPA.
_REDUCED_IPA = {"AH": "ə", "ER": "ɚ"}

_ARPABET_TO_RESPELLING = {
    "AA": "ah", "AE": "a", "AH": "uh", "AO": "aw", "AW": "ow", "AY": "y",
    "EH": "e", "ER": "ur", "EY": "ay", "IH": "i", "IY": "ee", "OW": "oh",
    "OY": "oy", "UH": "uu", "UW": "oo",
    "B": "b", "CH": "ch", "D": "d", "DH": "th", "F": "f", "G": "g",
    "HH": "h", "JH": "j", "K": "k", "L": "l", "M": "m", "N": "n",
    "NG": "ng", "P": "p", "R": "r", "S": "s", "SH": "sh", "T": "t",
    "TH": "th", "V": "v", "W": "w", "Y": "y", "Z": "z", "ZH": "zh",
}

#: Consonant pairs that may begin an English syllable, so they move to the
#: following onset rather than closing the previous syllable.
_VALID_ONSETS = {
    ("P", "L"), ("P", "R"), ("B", "L"), ("B", "R"),
    ("T", "R"), ("T", "W"), ("D", "R"), ("D", "W"),
    ("K", "L"), ("K", "R"), ("K", "W"), ("G", "L"), ("G", "R"), ("G", "W"),
    ("F", "L"), ("F", "R"), ("TH", "R"), ("TH", "W"),
    ("SH", "R"), ("S", "L"), ("S", "P"), ("S", "T"), ("S", "K"),
    ("S", "M"), ("S", "N"), ("S", "W"), ("HH", "W"),
    ("P", "Y"), ("B", "Y"), ("K", "Y"), ("F", "Y"), ("M", "Y"),
    ("V", "Y"), ("HH", "Y"), ("N", "Y"),
}

_STRESS_RE = re.compile(r"([A-Z]+)([0-2]?)$")


@dataclass
class Syllable:
    """One syllable: its phones and how strongly it is stressed."""

    phones: List[str]
    stress: int = 0

    @property
    def vowel_index(self) -> int:
        for index, phone in enumerate(self.phones):
            if base_phone(phone) in VOWELS:
                return index
        return -1


@dataclass
class Pronunciation:
    """A word's pronunciation in every form the application shows."""

    arpabet: str = ""
    ipa: str = ""
    respelling: str = ""
    syllable_count: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.arpabet


def base_phone(phone: str) -> str:
    """``AH1`` -> ``AH``."""
    match = _STRESS_RE.match(phone)
    return match.group(1) if match else phone


def stress_of(phone: str) -> int:
    """``AH1`` -> 1; consonants and unmarked vowels -> 0."""
    match = _STRESS_RE.match(phone)
    if not match or not match.group(2):
        return 0
    return int(match.group(2))


def syllabify(phones: Sequence[str]) -> List[Syllable]:
    """Group phones into syllables using a maximal-onset heuristic.

    Each syllable runs from its own onset to the start of the next one, so
    coda consonants stay attached to the syllable they close.
    """
    cleaned = [p for p in phones if p]
    vowel_positions = [i for i, p in enumerate(cleaned) if base_phone(p) in VOWELS]
    if not vowel_positions:
        return [Syllable(phones=list(cleaned))] if cleaned else []

    # Where each syllable begins. The first one swallows any leading consonants.
    starts: List[int] = [0]
    for order in range(1, len(vowel_positions)):
        vowel_index = vowel_positions[order]
        previous_vowel = vowel_positions[order - 1]
        between = cleaned[previous_vowel + 1:vowel_index]
        if not between:
            starts.append(vowel_index)
        elif len(between) == 1:
            # A single consonant between vowels opens the next syllable.
            starts.append(vowel_index - 1)
        else:
            # Take two if they form a legal English onset, otherwise one; the
            # rest stay behind as the previous syllable's coda.
            pair = (base_phone(between[-2]), base_phone(between[-1]))
            starts.append(vowel_index - (2 if pair in _VALID_ONSETS else 1))

    syllables: List[Syllable] = []
    for order, start in enumerate(starts):
        end = starts[order + 1] if order + 1 < len(starts) else len(cleaned)
        syllables.append(Syllable(
            phones=list(cleaned[start:end]),
            stress=stress_of(cleaned[vowel_positions[order]]),
        ))
    return syllables


def to_ipa(phones: Sequence[str]) -> str:
    """Render phones as IPA with syllable and stress marks."""
    syllables = syllabify(phones)
    if not syllables:
        return ""

    parts: List[str] = []
    for syllable in syllables:
        sounds = []
        for phone in syllable.phones:
            base = base_phone(phone)
            if base in _REDUCED_IPA and stress_of(phone) == 0:
                sounds.append(_REDUCED_IPA[base])
            else:
                sounds.append(_ARPABET_TO_IPA.get(base, ""))
        marker = "ˈ" if syllable.stress == 1 else "ˌ" if syllable.stress == 2 else ""
        parts.append(marker + "".join(sounds))

    return ".".join(parts)


def to_respelling(phones: Sequence[str]) -> str:
    """Render phones as a plain-English respelling, stressed part in capitals."""
    syllables = syllabify(phones)
    if not syllables:
        return ""

    parts: List[str] = []
    for syllable in syllables:
        text = "".join(
            _ARPABET_TO_RESPELLING.get(base_phone(p), "") for p in syllable.phones
        )
        parts.append(text.upper() if syllable.stress == 1 else text)

    # A single syllable is always the stressed one; capitalising it adds nothing.
    if len(parts) == 1:
        return parts[0].lower()
    return "-".join(part for part in parts if part)


def analyse(arpabet: str) -> Pronunciation:
    """Build every rendering from a space-separated ARPAbet string."""
    phones = arpabet.split()
    if not phones:
        return Pronunciation()
    return Pronunciation(
        arpabet=" ".join(phones),
        ipa=to_ipa(phones),
        respelling=to_respelling(phones),
        syllable_count=len(syllabify(phones)),
    )


_CMUDICT_LINE_RE = re.compile(r"^([^\s]+)\s+(.+?)\s*(?:#.*)?$")
_VARIANT_RE = re.compile(r"\(\d+\)$")


def parse_cmudict(lines) -> Dict[str, str]:
    """Read cmudict, keeping the first (preferred) pronunciation per word."""
    pronunciations: Dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith(";;;"):
            continue
        match = _CMUDICT_LINE_RE.match(line)
        if not match:
            continue
        word, phones = match.group(1), match.group(2)
        # "record(2)" is an alternative reading; the first one wins.
        if _VARIANT_RE.search(word):
            continue
        word = word.lower()
        if word not in pronunciations and phones.strip():
            pronunciations[word] = phones.strip()
    return pronunciations


def lookup(word: str, table: Dict[str, str]) -> Optional[Tuple[str, Pronunciation]]:
    """Find ``word`` in a cmudict table, trying simple variants."""
    candidates = [word.lower(), word.lower().replace("-", " "),
                  word.lower().replace(" ", "-"), word.lower().replace("'", "")]
    for candidate in candidates:
        arpabet = table.get(candidate)
        if arpabet:
            return candidate, analyse(arpabet)
    return None
