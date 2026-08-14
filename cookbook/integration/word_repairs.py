"""Repair what ``IngredientParser`` makes of the household's ingredient lines (REQ-007).

``IngredientParser`` takes the token after the amount as the unit. In German that token is
usually an adjective, so ``1 reife Avocado`` arrives as one *reife* of *Avocado*, and where the
token is a noun the real food is pushed out of the food slot entirely - ``1 Eigelb zum
Bestreichen`` becomes a row with no egg yolk in it.

This module is the fork's answer, and it is deliberately **one rule plus a few closed lists**
rather than a repair per observed word (REQ-007 Decision 2):

    the food is the thing you buy - the last capitalised noun;
    everything that qualifies it becomes a note.

German does the work: attributive adjectives are lowercase and nouns are capitalised, so the
capitalisation in the line already says which token is the food. The lists below only name
what capitalisation cannot: where a note begins (cut words), what says nothing at all (drop
words), what counts as a unit, and the handful of names the rule must not split.

Pure by design, like ``cookbook/helper/word_parser.py``: no Django, no models, no database, so
the rule can be run over a folder of documents on its own. It is applied by
``cookbook/integration/word.py`` and by nothing else - URL import and manual entry keep
Tandoor's own behaviour (Decision 11), and the shared ``IngredientParser`` is not touched
(Decision 1).

Two fixes run *before* parsing, because they change how the line tokenises at all
(Decision 4); everything else runs *after* it, where what the parser thought each token was is
known rather than guessed (Decision 3). A repair that cannot be made confidently is not made:
leaving a line exactly as the parser left it is always available and always safe (Decision 8).
"""
import re

# --------------------------------------------------------------------------------------
# The rule's data. Closed lists, in one file (Decision 5) - a restore of the pre-import dump
# would silently wipe Automation rows, and every re-import would then produce the old result.
# --------------------------------------------------------------------------------------

#: A note begins here. A preposition always opens a qualifier, wherever it stands:
#: 'Butter fuer die Form', 'Saft einer Limette', 'Thunfisch in Oel'.
CUT_PREPOSITIONS = frozenset({
    'als',
    'am',
    'auf',
    'aus',
    'bei',
    'beim',
    'bzw',
    'bzw.',
    'für',
    'fuer',
    'im',
    'in',
    'inkl',
    'mit',
    'nach',
    'ohne',
    'pro',
    'typ',
    'type',
    'vom',
    'zum',
    'zur',
    'z.b.',
    'zb',
})
# 'von' is deliberately not among them. It is the one preposition this collection uses to name
# what a thing was made *from* - 'Saft von 1 Zitrone', 'Schale von ½ Zitrone', 'Mark von 1
# Vanilleschote' - and the owner ruled that the fruit is the food there, not the juice. Cutting
# at it would keep 'Saft'. 'vom' stays a cut word: 'Brötchen vom Vortag' is bread, not a day.

#: A conjunction only opens a note once the food has been named - 'Sonnenblumenoel oder
#: Butterschmalz' is a choice between two foods, but 'frisches oder gefrorenes Basilikum' is
#: a choice between two adjectives and the noun is still ahead.
CUT_CONJUNCTIONS = frozenset({'oder', 'und', 'bzw.', 'beziehungsweise'})

#: Says nothing about what to buy, so it is dropped rather than noted: articles, and the
#: filler the collection opens a line with ('Etwas Zitronensaft', 'Verschiedene Kraeuter').
DROP_WORDS = frozenset({
    'ca',
    'ca.',
    'das',
    'dem',
    'den',
    'der',
    'des',
    'die',
    'ein',
    'eine',
    'einem',
    'einen',
    'einer',
    'eines',
    'einige',
    'einigen',
    'etwa',
    'etwas',
    'eventuell',
    'evtl',
    'evtl.',
    'je',
    'nen',
    'verschiedene',
    'verschiedenen',
    'verschiedener',
    'verschiedenes',
    'wenig',
    'wenige',
})

#: What counts as a unit, lower-cased alias -> the spelling a Unit row gets. Anything not
#: named here is not a unit, whatever position it turned up in. Plurals and the spelled-out
#: forms fold into the singular so 'EL', 'El' and 'Esslöffel' meet as one Unit.
KNOWN_UNITS = {
    'becher': 'Becher',
    'beutel': 'Beutel',
    'blatt': 'Blatt',
    'blätter': 'Blatt',
    'bund': 'Bund',
    'cl': 'cl',
    'cm': 'cm',
    'dl': 'dl',
    'dose': 'Dose',
    'dosen': 'Dose',
    'el': 'El',
    'esslöffel': 'El',
    'flasche': 'Flasche',
    'flaschen': 'Flasche',
    'fläschchen': 'Fläschchen',
    'g': 'g',
    'glas': 'Glas',
    'gläser': 'Glas',
    'gramm': 'g',
    'handvoll': 'Handvoll',
    'kg': 'kg',
    'knolle': 'Knolle',
    'knollen': 'Knolle',
    'kopf': 'Kopf',
    'köpfe': 'Kopf',
    'l': 'l',
    'liter': 'l',
    'messerspitze': 'Messerspitze',
    'messerspitzen': 'Messerspitze',
    'mg': 'mg',
    'ml': 'ml',
    'msp': 'Messerspitze',
    'msp.': 'Messerspitze',
    'paar': 'Paar',
    'pck': 'Päckchen',
    'pck.': 'Päckchen',
    'pkg': 'Päckchen',
    'portion': 'Portion',
    'portionen': 'Portion',
    'prise': 'Prise',
    'prisen': 'Prise',
    'päckchen': 'Päckchen',
    'scheibe': 'Scheibe',
    'scheiben': 'Scheibe',
    'schnapsglas': 'Schnapsglas',
    'schuss': 'Schuss',
    'spitzer': 'Spitzer',
    'stange': 'Stange',
    'stangen': 'Stange',
    'stiel': 'Stiel',
    'stiele': 'Stiel',
    'streifen': 'Streifen',
    'stängel': 'Stängel',
    'stück': 'Stück',
    'tasse': 'Tasse',
    'tassen': 'Tasse',
    'teelöffel': 'Tl',
    'tl': 'Tl',
    'tropfen': 'Tropfen',
    'würfel': 'Würfel',
    'zweig': 'Zweig',
    'zweige': 'Zweig',
}

#: A household measure that is really a quantity, applied to the amount: 1 Tasse = 180 ml.
UNIT_CONVERSIONS = {
    'Tasse': (180, 'ml'),
}

#: Genuine multi-word names, lower-cased. The rule would split these at their last capitalised
#: token or drop a qualifier the name needs; 'Crème fraîche' needs no entry, because the rule
#: already leaves it whole (Decision 7).
KEEP_WHOLE = {
    'ginger ale': 'Ginger Ale',
    'lime juice': 'Lime Juice',
    'paprikapulver edelsüß': 'Paprikapulver edelsüß',
    'rote bete': 'Rote Bete',
    'saure sahne': 'Saure Sahne',
    'wiener würstchen': 'Wiener Würstchen',
}

#: Plural and spelling pairs, lower-cased -> the food row they all mean. ``get_food`` matches
#: exactly, so without these 'Avocado' and 'Avocados' are two foods that never roll up.
FOOD_ALIASES = {
    'avocados': 'Avocado',
    'bananen': 'Banane',
    'champignons': 'Champignon',
    'eier': 'Ei',
    'kartoffeln': 'Kartoffel',
    'karotten': 'Karotte',
    'limetten': 'Limette',
    'möhren': 'Möhre',
    'orangen': 'Orange',
    'paprikaschoten': 'Paprika',
    'tomaten': 'Tomate',
    'zitronen': 'Zitrone',
    'zwiebeln': 'Zwiebel',
}

#: De-inflection irregulars: German drops the stem's own 'e' before an ending, so the general
#: rule below would leave 'saure' as 'saur'. Lower-cased inflected form -> the plain adjective.
ADJECTIVE_STEMS = {
    'dunkle': 'dunkel',
    'dunklem': 'dunkel',
    'dunklen': 'dunkel',
    'dunkler': 'dunkel',
    'dunkles': 'dunkel',
    'edle': 'edel',
    'hohe': 'hoch',
    'hohem': 'hoch',
    'hohen': 'hoch',
    'hoher': 'hoch',
    'hohes': 'hoch',
    'edlem': 'edel',
    'edlen': 'edel',
    'edler': 'edel',
    'edles': 'edel',
    'saure': 'sauer',
    'saurem': 'sauer',
    'sauren': 'sauer',
    'saurer': 'sauer',
    'saures': 'sauer',
    'teure': 'teuer',
    'teuren': 'teuer',
    'teurer': 'teuer',
}

# --------------------------------------------------------------------------------------
# The rule
# --------------------------------------------------------------------------------------

#: Attributive endings, longest first. Stripped only from a lowercase word, which in German
#: means it is not the food - so a wrong strip costs a note's spelling, never a food.
ADJECTIVE_ENDINGS = ('en', 'em', 'er', 'es', 'e')

#: Below this the remainder is not a plausible stem and the word is left as written.
MINIMUM_STEM = 3

#: A flour or lye grade: the number is the data, the German suffix is not (Decision 6).
GRADE = re.compile(r'^(\d+)(%)?(?:er|ige[rnsm]?|ig)$', re.IGNORECASE)

#: The same, anywhere in a note. The owner ruled on 2026-08-14 that a grade reads as a bare
#: number wherever it ends up, including in a note the parser itself wrote: the collection
#: spells the same flour '1050er Weizenmehl' and 'Weizenmehl (550er)', and the two forms are
#: meant to read alike once they meet as one food. This is the one place a repair rewrites
#: something the parser already had right - see the plan for the AC3/AC5 fork it settles.
GRADE_IN_NOTE = re.compile(r'\b(\d+)(%)?(?:er|ige[rnsm]?|ig)\b', re.IGNORECASE)

#: 'Weizenmehl · Typ 550' and 'Weizenmehl · 550' are the same flour, and the owner prefers the
#: shorter one (ruled 2026-08-14), so the word in front of the number goes the way the suffix
#: behind it does.
GRADE_WORD = re.compile(r'\btyp(?:en?)?\b[\s.:]*(?=\d)', re.IGNORECASE)

#: '4–6 Eier' has to become '4 - 6 Eier' before the parser's own range handling can fire.
RANGE_DASH = re.compile(r'(?<=[\d½¼¾])\s*[–—]\s*(?=[\d½¼¾])')

#: ...but not on a line that already carries a parenthetical. The parser rewrites a range by
#: moving it to the end of the line, where it lands behind that parenthetical and the food
#: phrase swallows the brackets: '4-6 Paprika (rot, gelb, grün)' would become the food
#: 'Paprika (rot, gelb, grün)'. Left as it is, the range surfaces as a bogus unit instead,
#: which the unit repair below turns into a note without touching the food.
RANGE_DASH_BLOCKED = re.compile(r'[()]')

#: 'Je 1 rote und gelbe Paprika' is two ingredients written as one line, and 'Je 1 gelbe,
#: grüne und rote Paprika' is three. Each variant is a single word, which is what keeps
#: 'Je 200 g Mehl und Zucker für den Teig' - where the two nouns do not share a qualifier -
#: out of this.
JE_LINE = re.compile(r'^je\s+(?P<amount>[\d.,/½¼¾]+)\s+(?P<head>\S+(?:,\s+\S+)*)\s+und\s+(?P<last>\S+)\s+(?P<rest>\S.*)$', re.IGNORECASE)

#: Punctuation a token may carry that must not decide whether it is a cut or drop word.
EDGE_PUNCTUATION = ',;:.'


def prepare_line(line):
    """The two fixes that have to happen before tokenising. Returns one line per variant."""
    prepared = line.strip()
    if not RANGE_DASH_BLOCKED.search(prepared):
        prepared = RANGE_DASH.sub(' - ', prepared)

    match = JE_LINE.match(prepared)
    if match:
        variants = [part.strip() for part in match.group('head').split(',')] + [match.group('last')]
        return [f'{match.group("amount")} {variant} {match.group("rest")}' for variant in variants]
    return [prepared]


def repair(line, amount, unit, food, note):
    """What the parser made of one line, put right. Returns ``(amount, unit, food, note)``.

    ``line`` is the line as handed to the parser, needed for the one case the parsed values
    cannot show on their own: a grade like ``1050er`` read as an amount plus a unit.
    """
    if not food or not food.strip():
        return amount, unit, food, note

    notes = []
    amount, unit, grade_note = _grade_read_as_amount(line, amount, unit)
    notes += grade_note

    unit, food, unit_notes = _repair_unit(unit, food)
    notes += unit_notes

    food, note = _rejoin_comma_split(line, food, note)

    food, food_notes = _repair_food(food, line)
    notes += food_notes

    unit, food = _canonical(unit, food)
    amount, unit = _convert(amount, unit)

    return amount, unit, food, _grades_reduced(_joined(notes + ([note] if note else [])))


def _rejoin_comma_split(line, food, note):
    """Put back a phrase the parser cut at a comma, when the cut left the food behind.

    ``6 große, mehlig kochende Kartoffeln`` parses to the food *große* noted *mehlig kochende
    Kartoffeln* - the comma is where the parser guessed the food ended, and the noun says it
    guessed wrong. Only a plain remainder is rejoined; anything with a bracket in it is the
    parser's own note handling and is left alone.
    """
    if not note or '(' in note or ')' in note or '(' in food or ')' in food:
        return food, note
    if f'{food}, {note}' not in line:
        return food, note
    if any(token[:1].isupper() for token in food.split()):
        return food, note
    return f'{food} {note}', ''


def _grade_read_as_amount(line, amount, unit):
    """``1050er Weizenmehl`` parses as 1050 *er* of flour. The grade is not an amount."""
    tokens = line.split()
    if not (tokens and unit):
        return amount, unit, []
    written = f'{amount:g}{unit}'
    if tokens[0] != written:
        return amount, unit, []
    grade = _grade(tokens[0])
    if grade is None:
        return amount, unit, []
    return 0, None, [grade]


def _repair_unit(unit, food):
    """Decide what the token in the unit slot really was, and recover a stranded unit."""
    notes = []

    if unit:
        known = KNOWN_UNITS.get(unit.lower())
        if known:
            unit = known
        elif not unit.replace('-', '').isalpha():
            # a range fragment or a stray symbol - not a unit and not a word either
            unit, notes = None, [unit]
        elif unit[0].islower():
            unit, notes = None, [_de_inflect(unit)]
        else:
            # a capitalised noun in the unit slot is the food, pushed out of its own slot
            unit, food = None, f'{unit} {food}'

    if unit is None:
        tokens = food.split()
        known = KNOWN_UNITS.get(tokens[0].lower()) if len(tokens) > 1 else None
        if known:
            unit, food = known, ' '.join(tokens[1:])

    return unit, food, notes


def _repair_food(food, line):
    """The food is the last capitalised noun; what qualifies it becomes a note."""
    if food.lower() in KEEP_WHOLE:
        return food, []
    if '(' in food or ')' in food:
        # the parser's own note handling is in play here; re-cutting the phrase is what
        # turned '5-6 säuerliche Äpfel (z.B. Braeburn)' into the food 'Braeburn)'
        return food, []

    tokens = _in_written_order(food.split(), line)
    notes = []

    cut = _cut_at(tokens)
    if cut == 0:
        return food, []
    if cut is not None:
        notes.append(' '.join(tokens[cut:]))
        tokens = tokens[:cut]

    tokens = [token for token in tokens if _plain(token) not in DROP_WORDS]
    if not tokens:
        return food, []

    if ' '.join(tokens).lower() in KEEP_WHOLE:
        return ' '.join(tokens), notes

    start = next((i for i in range(len(tokens) - 1, -1, -1) if tokens[i][:1].isupper()), None)
    if start is None:
        return food, []

    repaired = ' '.join(tokens[start:])
    if _plain(repaired) in DROP_WORDS | CUT_PREPOSITIONS | CUT_CONJUNCTIONS:
        # a word the lists call filler is never the answer, however it got capitalised
        return food, []

    return repaired, [_as_note(token) for token in tokens[:start]] + notes


def _in_written_order(tokens, line):
    """The phrase back in the order the household wrote it.

    ``IngredientParser`` moves an amount it finds late in a line to the front, so
    ``Saft von 1 Zitrone`` reaches the rule as ``1 Zitrone Saft von`` and the last capitalised
    token is no longer the noun the line ends on. Reordering is a no-op for every line the
    parser did not shuffle, and is skipped when a token cannot be found in the line at all.
    """
    written = line.split()
    positions = {}
    for index, token in enumerate(written):
        positions.setdefault(token, index)

    def position(token):
        if token in positions:
            return positions[token]
        # the parser trims as it goes ('1-2' reaches the food phrase as '1-'), so fall back
        # to the first written token this one opens
        return next((index for index, word in enumerate(written) if word.startswith(token)), None)

    found = [position(token) for token in tokens]
    if None in found:
        return tokens
    return [token for _, token in sorted(zip(found, tokens), key=lambda pair: pair[0])]


def _cut_at(tokens):
    """Where the note begins in a food phrase, or ``None`` if it does not begin at all."""
    for i, token in enumerate(tokens):
        word = _plain(token)
        if word in CUT_PREPOSITIONS:
            return i
        if word in CUT_CONJUNCTIONS and _joins_two_nouns(tokens, i):
            return i
    return None


def _joins_two_nouns(tokens, i):
    """Is the conjunction at ``i`` a choice between two foods, or between two qualifiers?

    Two foods, so the first one is the food and the rest is a note:

        Sonnenblumenöl oder Butterschmalz      Brötchen oder 3 Scheiben Toast

    Two qualifiers, so the food is still ahead and there is nothing to cut:

        Frische oder getrocknete Petersilie    frisches oder gefrorenes Basilikum
        Rispen- oder Cocktailtomaten           (an elided compound is only half a word)
    """
    if not 0 < i < len(tokens) - 1:
        return False
    before, after = tokens[i - 1], tokens[i + 1]
    return before[:1].isupper() and not before.endswith('-') and not after[:1].islower()


def _canonical(unit, food):
    """Fold the spellings that mean the same row into one."""
    food = food.strip(',;: ') or food
    if food.endswith(')') and '(' not in food:
        # a bracket with no partner is not part of a name - '(viel Dill)' leaves 'Dill)'
        food = food[:-1] or food
    return unit, KEEP_WHOLE.get(food.lower()) or FOOD_ALIASES.get(food.lower(), food)


def _convert(amount, unit):
    """A household measure that is really a quantity."""
    if unit in UNIT_CONVERSIONS and amount:
        factor, converted = UNIT_CONVERSIONS[unit]
        return amount * factor, converted
    return amount, unit


def _as_note(token):
    """A qualifier, as it belongs in a note: nouns as written, adjectives uninflected."""
    grade = _grade(token)
    if grade is not None:
        return grade
    if token[:1].isupper():
        return token
    return _de_inflect(token)


def _de_inflect(word):
    """'geriebener' -> 'gerieben'. Only ever applied to a lowercase word."""
    lowered = word.lower()
    if lowered in ADJECTIVE_STEMS:
        return ADJECTIVE_STEMS[lowered]
    for ending in ADJECTIVE_ENDINGS:
        if lowered.endswith(ending) and len(lowered) - len(ending) >= MINIMUM_STEM:
            return lowered[:-len(ending)]
    return lowered


def _grades_reduced(note):
    """'Typ 550er' -> '550' wherever it stands in a note, the parser's own wording included."""
    return GRADE_WORD.sub('', GRADE_IN_NOTE.sub(lambda match: match.group(1) + (match.group(2) or ''), note))


def _grade(token):
    """'1050er' -> '1050', '4%ige' -> '4%', anything else -> None."""
    match = GRADE.match(token.strip(EDGE_PUNCTUATION))
    return None if not match else match.group(1) + (match.group(2) or '')


def _plain(token):
    return token.strip(EDGE_PUNCTUATION).lower()


def _joined(parts):
    return ' '.join(part.strip() for part in parts if part and part.strip()).strip()
