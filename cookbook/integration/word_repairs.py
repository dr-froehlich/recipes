"""Repair what ``IngredientParser`` makes of the household's ingredient lines (REQ-007).

``IngredientParser`` takes the token after the amount as the unit. In German that token is
usually an adjective, so ``1 reife Avocado`` arrives as one *reife* of *Avocado*, and where the
token is a noun the real food is pushed out of the food slot entirely - ``1 Eigelb zum
Bestreichen`` becomes a row with no egg yolk in it.

This module is the fork's answer, and it is deliberately **one rule plus a few closed lists**
rather than a repair per observed word (REQ-007 Decision 2):

    the food is what you buy, written out in full;
    what you *do* with it, and how you judge it at the shelf, becomes a note.

The seam sits there and not anywhere else because of where the information has to survive to.
Tandoor's shopping list renders amount, unit and food and **never the note** - see
``vue3/src/components/display/ShoppingLineItem.vue``, which does not mention the field. So a
qualifier that distinguishes one purchase from another has to be *in the food name* or it is
gone by the time anyone is standing in the shop. ``Paprika`` noted *rot* is a shopping list that
says "Paprika"; ``Paprika rot`` is one that tells you which to pick up. That is REQ-007's
rework of 2026-08-14, and it inverts the rule the first implementation was built on.

Which side a qualifier lands on:

* an **extraction phrase** - the part you take out of a whole product - notes the part and
  keeps the product: ``Saft von 1 Zitrone`` is one *Zitrone* noted *Saft von*, because a lemon
  is what you buy;
* a **preparation** you carry out at home is a note (``gehackte Zwiebel`` -> *Zwiebel* ·
  gehackt), recognised by the shape of a German past participle rather than by a word list -
  except for the handful in ``PRODUCT_FORMS``, which name something sold that way;
* a **condition or a measure** is a note, because you do not buy ripeness, softness or the
  heap on a spoon: ``1 gehäufter Tl Senf`` is a heaped teaspoon of *Senf*;
* **everything else stays with the food**, de-inflected and written after the noun. That
  default is the whole point: an unlisted qualifier is never silently dropped, which is the
  failure the first implementation shipped. The cost is a longer food list, paid deliberately.

Names come out noun first - ``Weizenmehl 1050``, ``Paprika rot`` - so that every flour and
every pepper sorts together in the food list and hangs under one parent in the food tree.
``food_parent`` names that parent; the importer builds the tree with it.

German does most of the work, because attributive adjectives are lowercase, nouns are
capitalised, and a *post*-nominal adjective does not inflect at all - which is why
``Paprikapulver edelsüß`` and ``Crème fraîche`` survive with no entry naming them.

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

#: A note begins here. A preposition always opens a qualifier that describes handling or
#: purpose rather than the product: 'Butter für die Form', 'Thunfisch in Öl'.
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
    'vom',
    'zum',
    'zur',
    'z.b',
    'z.b.',
    'zb',
})
# 'von' is deliberately not among them: it belongs to the extraction phrases below, where the
# whole product is the food and the part is the note. 'vom' stays a cut word - 'Brötchen vom
# Vortag' is bread, not a day. 'typ' is not among them either; it introduces a grade, which
# after the rework belongs *in* the food name (GRADE_MARKERS).

#: A conjunction only opens a note once the food has been named - 'Sonnenblumenöl oder
#: Butterschmalz' is a choice between two foods, but 'frisches oder gefrorenes Basilikum' is
#: a choice between two qualifiers and the noun is still ahead.
CUT_CONJUNCTIONS = frozenset({'oder', 'und', 'bzw.', 'beziehungsweise'})

#: Says nothing about what to buy, so it is dropped rather than noted: articles, and the
#: filler the collection opens a line with ('Etwas Zitronensaft', 'Verschiedene Kräuter').
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
    'höchstens',
    'max',
    'max.',
    'maximal',
    'mind',
    'mind.',
    'mindestens',
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

#: 'Weizenmehl Typ 550' names a grade the way the packet does. The word is dropped and the
#: number stays, so the collection's three spellings - 'Typ 550', '550er' and '(550er)' -
#: all arrive at the same food, 'Weizenmehl 550' (owner's ruling, 2026-08-14).
GRADE_MARKERS = frozenset({'typ', 'type', 'typen'})

#: The part you take out of a product you buy whole. The product stays the food and the part
#: goes to the note, phrased the way the line phrased it (owner's ruling, 2026-08-14):
#: 'Saft von 1 Zitrone' is one Zitrone noted 'Saft von', because a lemon is what is on the
#: shopping list. A bare 'Saft' with no other noun beside it is still a food in its own right.
EXTRACTION_NOUNS = frozenset({
    'abrieb',
    'fruchtfleisch',
    'kerne',
    'mark',
    'saft',
    'schale',
    'schalenabrieb',
    'zesten',
})

#: Condition and measure. Neither is a thing you buy: ripeness and softness are judged at the
#: shelf or happen in the kitchen, and a heaped spoon qualifies the spoon. Deliberately short -
#: an adjective that is *not* here stays with the food, which is the safe direction.
#: 'frisch' is here because it is the unmarked case: plain 'Petersilie' is the fresh one and
#: 'Petersilie getrocknet' is the marked form. 'trocken' is *not* here - a trockener Weißwein
#: is a different bottle. Keys are the de-inflected form.
CONDITION_WORDS = frozenset({
    'alt',
    'altbacken',
    'frisch',
    'gehäuft',
    'gestrichen',
    'groß',
    'hart',
    'heiß',
    'kalt',
    'klein',
    'knapp',
    'lauwarm',
    'mittelgroß',
    'reichlich',
    'reif',
    'unreif',
    'warm',
    'weich',
    'zimmerwarm',
})

#: Past participles name a preparation and go to the note by shape alone (PARTICIPLE below),
#: with no word list - which is what keeps the 141-word tail out of this file. These are the
#: exceptions: a product that is *sold* in that state, so it belongs in the food name.
#: Keys are the de-inflected form.
PRODUCT_FORMS = frozenset({
    'gebeizt',
    'gefroren',
    'gemahlen',
    'gepökelt',
    'gerieben',
    'geräuchert',
    'gesalzen',
    'geschält',
    'getrocknet',
    'gezuckert',
    'mariniert',
    'passiert',
    'tiefgefroren',
    'tiefgekühlt',
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

#: Genuine multi-word names, lower-cased. The rule would either split these or hang them under
#: a nonsense parent in the food tree. Far shorter than it was before the rework: a post-nominal
#: adjective is now kept as written, so 'Paprikapulver edelsüß' needs no entry either - only
#: names whose *first* word is not the head noun do (Decision 7).
KEEP_WHOLE = {
    'creme fraiche': 'Crème fraîche',
    'crème fraiche': 'Crème fraîche',
    'crème fraîche': 'Crème fraîche',
    'ginger ale': 'Ginger Ale',
    'kartoffel fest kochend': 'Kartoffel festkochend',
    'lime juice': 'Lime Juice',
    'rote bete': 'Rote Bete',
    'saure sahne': 'Saure Sahne',
    'wiener würstchen': 'Wiener Würstchen',
}

#: Plural and spelling pairs, lower-cased -> the food row they all mean. ``get_food`` matches
#: exactly, so without these 'Avocado' and 'Avocados' are two foods that never roll up. Applied
#: to the head noun before its qualifiers are appended, so 'säuerliche Äpfel' reaches
#: 'Apfel säuerlich' rather than inventing a second 'Äpfel' tree.
FOOD_ALIASES = {
    'avocados': 'Avocado',
    'bananen': 'Banane',
    'champignons': 'Champignon',
    'eier': 'Ei',
    'erbsen': 'Erbse',
    'haselnüsse': 'Haselnuss',
    'kartoffeln': 'Kartoffel',
    'karotten': 'Karotte',
    'limetten': 'Limette',
    'mandeln': 'Mandel',
    'möhren': 'Möhre',
    'orangen': 'Orange',
    'paprikaschoten': 'Paprika',
    'tomaten': 'Tomate',
    'zitronen': 'Zitrone',
    'zwiebeln': 'Zwiebel',
    'äpfel': 'Apfel',
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
    'edlem': 'edel',
    'edlen': 'edel',
    'edler': 'edel',
    'edles': 'edel',
    'große': 'groß',
    'großem': 'groß',
    'großen': 'groß',
    'großer': 'groß',
    'großes': 'groß',
    'hohe': 'hoch',
    'hohem': 'hoch',
    'hohen': 'hoch',
    'hoher': 'hoch',
    'hohes': 'hoch',
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
#: means it is not the head noun - so a wrong strip costs a qualifier's spelling, never a food.
ADJECTIVE_ENDINGS = ('en', 'em', 'er', 'es', 'e')

#: Below this the remainder is not a plausible stem and the word is left as written.
MINIMUM_STEM = 3

#: A German past participle, which names something done to the food: ge- somewhere at the
#: front, -t or -en at the back. Matching by shape rather than by a list is what keeps the
#: collection's 141-word adjective tail out of this file entirely. The leading group catches
#: the separable and compound forms - 'abgerieben', 'tiefgekühlt'.
PARTICIPLE = re.compile(r'^(?:[a-zäöüß]*ge[a-zäöüß]{2,}(?:t|en)|(?:be|emp|ent|er|miss|ver|zer)[a-zäöüß]{2,}(?:t|en)|[a-zäöüß]{3,}iert)$')

#: A flour or lye grade: the number is the data, the German suffix is not (Decision 6).
GRADE = re.compile(r'^(\d+)(%)?(?:er|ige[rnsm]?|ig)$', re.IGNORECASE)

#: The same, anywhere in the note the parser itself wrote. '200 g Weizenmehl (550er)' arrives
#: as flour noted '550er', and after the rework that grade belongs in the food name, so the
#: collection's two spellings meet as the one food 'Weizenmehl 550'.
GRADE_IN_NOTE = re.compile(r'^\s*(?:typ(?:en?)?\b[\s.:]*)?(\d+)\s*(%)?\s*(?:er|ige[rnsm]?|ig)?\s*$', re.IGNORECASE)

#: What is left of a range the dash fix was blocked from normalising: the parser reads
#: '5–6 Äpfel (…)' as five of unit '–6'.
RANGE_FRAGMENT = re.compile(r'^[–—-]\s*(\d+(?:[.,]\d+)?|[½¼¾])$')

#: What the household put in brackets, which the parser reads through rather than keeps.
PARENTHETICAL = re.compile(r'\(([^)]*)\)')

#: A token that is nothing but a quantity.
BARE_NUMBER = re.compile(r'^\d+(?:[.,/]\d+)?$|^[½¼¾]$')

#: An amount stranded at the end of a note, as 'Zitrone, Saft von 1/2' leaves it.
AMOUNT_IN_NOTE = re.compile(r'(?:^|\s)(\d+/\d+|\d+(?:[.,]\d+)?|[½¼¾])\s*$')

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

    ``line`` is the line as handed to the parser, needed for the two cases the parsed values
    cannot show on their own: a grade like ``1050er`` read as an amount plus a unit, and a
    phrase the parser transposed on its way to the food slot.
    """
    if not food or not food.strip():
        return amount, unit, food, note

    notes, qualifiers = [], []

    amount, unit, grade = _grade_read_as_amount(line, amount, unit)
    qualifiers += grade

    amount, unit, food, unit_notes = _repair_unit(amount, unit, food)
    notes += unit_notes

    food, note = _rejoin_comma_split(line, food, note)
    amount, food = _half_out_of_food(amount, food)
    amount, note = _amount_out_of_note(amount, note)
    note, note_qualifiers = _qualifiers_out_of_note(note)
    qualifiers += note_qualifiers

    food, food_qualifiers, food_notes = _repair_food(food, line)
    qualifiers += food_qualifiers
    notes += food_notes

    unit, food = _canonical(unit, _qualified(food, qualifiers))
    amount, unit = _convert(amount, unit)

    return amount, unit, food, _parenthetical_note(line, _joined(notes + ([note] if note else [])), food)


def food_parent(food):
    """The head noun a qualified food hangs under in the food tree, or ``None``.

    Because names come out noun first, the parent is the first token whenever every token
    behind it is a qualifier - ``Weizenmehl 1050`` under ``Weizenmehl``, ``Paprika rot`` under
    ``Paprika``. A second capitalised token means the name is a name rather than a noun plus
    its qualifiers (``Wiener Würstchen``, ``Rote Bete``), and those stay at the root.
    """
    if not food:
        return None
    if food.lower() in KEEP_WHOLE:
        return None
    tokens = food.split()
    if len(tokens) < 2 or not tokens[0][:1].isupper():
        return None
    if any(token[:1].isupper() for token in tokens[1:]):
        return None
    return tokens[0]


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
    if tokens[0] != f'{amount:g}{unit}':
        return amount, unit, []
    grade = _grade(tokens[0])
    if grade is None:
        return amount, unit, []
    return 0, None, [grade]


def _amount_out_of_note(amount, note):
    """An amount the parser could not place: ``Zitrone, Saft von 1/2`` leaves the half behind.

    Taken only when the parse found no amount at all, and only from the end of the note, which
    is where the parser puts what it could not fit anywhere else.
    """
    if amount or not note:
        return amount, note
    match = AMOUNT_IN_NOTE.search(note)
    if not match:
        return amount, note
    return _number(match.group(1)), note[:match.start()].strip(' ,;')


def _qualifiers_out_of_note(note):
    """What the parser parked in a note that the rework says belongs in the food name.

    Two shapes, and nothing else - a note with more in it is the household saying something,
    and the food name is not the place for it:

    * a bare grade. ``200 g Weizenmehl (550er)`` reaches here as flour noted *550er*, and the
      grade has to join the name or this spelling never meets ``1050er Weizenmehl``.
    * a single lowercase qualifier the parser stranded. ``5-6 säuerliche Äpfel (z.B.
      Braeburn)`` reaches here as apples noted *säuerliche*, and dropping the word into a note
      nobody sees is the failure this rework exists to fix. A preparation or a condition is
      left where it is - ``1 Zwiebel, gehackt`` keeps its note.
    """
    if not note:
        return note, []

    grade = GRADE_IN_NOTE.match(note)
    if grade:
        return '', [grade.group(1) + (grade.group(2) or '')]

    stranded = note.strip()
    if stranded.isalpha() and stranded[:1].islower() and _plain(stranded) not in DROP_WORDS:
        word = _de_inflect(stranded)
        if word not in CONDITION_WORDS and not PARTICIPLE.match(word) and word not in DROP_WORDS:
            return '', [word]

    return note, []


def _parenthetical_note(line, note, food):
    """What the household wrote in brackets, as it wrote it.

    The parser reaches into a parenthetical for an amount and a unit and hands back what is
    left, so ``(es geht auch 1 El getrockneter Thymian)`` arrives as *es geht auch getrockneter
    Thymian* - and for ``(z.B. Braeburn)`` it hands back nothing at all. The bracket text is
    the household speaking and the safest thing to show is what it actually said.

    A parenthetical that is only a grade is already in the food name and is not repeated here.
    """
    named = {token.lower() for token in food.split()}
    parts = [part.strip() for part in PARENTHETICAL.findall(line) if part.strip()]
    # a bracket holding one qualifier that already reached the food name is not repeated as a
    # note: '(550er)' is the food's grade and '(edelsüß)' is the food's own word, and saying
    # either of them twice is how 'Paprikapulver edelsüß' and 'Paprikapulver' · edelsüß became
    # two different foods in the corpus
    parts = [part for part in parts if part.lower() not in named and _de_inflect(part) not in named]
    if not parts:
        return note

    written = ' '.join(parts)
    if not note or written == note or written in note:
        return note or written

    # whatever the parser salvaged of this same bracket is said better by the bracket itself,
    # so those words are dropped rather than repeated: '3,' beside '3,5 g' helps nobody
    kept = [word for word in note.split() if not any(w == word or w.startswith(word) for w in written.split())]
    return _joined(kept + [written])


def _repair_unit(amount, unit, food):
    """Decide what the token in the unit slot really was, and recover a stranded unit.

    A word that is not a known unit is handed back to the front of the food phrase rather than
    classified here, because the food repair is the one place that knows whether a qualifier
    belongs in the name or in the note. Before the rework this method decided it, which is how
    ``1 rote Paprika`` lost its colour to a note nobody ever sees.
    """
    notes = []

    if unit:
        known = KNOWN_UNITS.get(unit.lower())
        if known:
            unit = known
        elif RANGE_FRAGMENT.match(unit):
            # the tail of a range the dash fix was not allowed to touch, because the line
            # also carries a parenthetical - '5–6 säuerliche Äpfel (z.B. Braeburn)'. The
            # amount already holds the bottom of the range, so the note can say both.
            unit, notes = None, [f'{amount:g} - {RANGE_FRAGMENT.match(unit).group(1)}']
        elif not unit.replace('-', '').isalpha():
            # a stray symbol - not a unit and not a word either
            unit, notes = None, [unit]
        else:
            unit, food = None, f'{unit} {food}'

    if unit is None:
        unit, food = _stranded_unit(food)
    else:
        # a unit was found *and* the food still leads with a quantity, which happens when the
        # parser reached into a parenthetical for its own: '½ Bund Thymian (… 1 El …)' is read
        # as one El. Two quantities cannot both be right, and the line's own comes first.
        amount, unit, food = _leading_quantity(amount, unit, food)

    return amount, unit, food, notes


def _half_out_of_food(amount, food):
    """``Saft einer halben Zitrone`` is half a lemon, not a lemon qualified as *halb*.

    The collection writes a half both ways, ``½`` and ``halbe``, and the parser reads only the
    first. Taken only when the parse found no amount, so a line that already has one keeps it.
    """
    if amount:
        return amount, food
    tokens = food.split()
    kept = [token for token in tokens if _de_inflect(token) != 'halb']
    if len(kept) == len(tokens) or not kept:
        return amount, food
    return 0.5, ' '.join(kept)


def _leading_quantity(amount, unit, food):
    """The quantity the line opens with, when the parser took its own from somewhere else.

    ``½ Bund Thymian (es geht auch 1 El getrockneter Thymian)`` is read as *1 El* of
    ``½ Bund Thymian`` - the parser reached into the parenthetical for its amount and unit and
    left the line's own behind in the food phrase. Whatever the food phrase still *starts*
    with is the real quantity, because nothing that qualifies a food stands in front of its
    noun as a bare number or a unit word.
    """
    tokens = food.split()
    leading_amount = leading_unit = None

    while len(tokens) > 1:
        if leading_amount is None and BARE_NUMBER.match(tokens[0]):
            leading_amount = _number(tokens.pop(0))
            continue
        if leading_unit is None and tokens[0].lower() in KNOWN_UNITS:
            leading_unit = KNOWN_UNITS[tokens.pop(0).lower()]
            continue
        break

    if leading_amount is None and leading_unit is None:
        return amount, unit, food
    return (leading_amount if leading_amount is not None else amount), (leading_unit or unit), ' '.join(tokens)


def _stranded_unit(food):
    """A real unit pushed into the food name: ``gehäufter Tl Senf`` is a teaspoon of mustard.

    Looked for in the first two tokens only, because a qualifier may stand in front of it, and
    never as the last token, which would leave no food behind.
    """
    tokens = food.split()
    for i, token in enumerate(tokens[:-1]):
        known = KNOWN_UNITS.get(token.lower())
        if known:
            return known, ' '.join(tokens[:i] + tokens[i + 1:])
        if not (BARE_NUMBER.match(token) or _is_adjective(token)):
            # a noun has been reached, so anything further along is part of the name
            break
    return None, food


def _repair_food(food, line):
    """The food is what you buy, written out in full. Returns ``(food, qualifiers, notes)``."""
    if food.lower() in KEEP_WHOLE:
        return KEEP_WHOLE[food.lower()], [], []
    food = PARENTHETICAL.sub(' ', food).strip()
    if '(' in food or ')' in food:
        # a bracket the line never closed. Re-cutting a phrase around one is what turned
        # '5-6 säuerliche Äpfel (z.B. Braeburn)' into the food 'Braeburn)', so leave it be
        return food, [], []
    if not food:
        return food, [], []

    tokens = _in_written_order(food.split(), line)
    notes = []

    cut = _cut_at(tokens)
    if cut == 0:
        return food, [], []
    if cut is not None:
        notes.append(' '.join(tokens[cut:]))
        tokens = tokens[:cut]

    tokens = _without_filler(tokens)
    if not tokens:
        return food, [], []
    if ' '.join(tokens).lower() in KEEP_WHOLE:
        return KEEP_WHOLE[' '.join(tokens).lower()], [], notes

    head = _head_noun(tokens)
    if head is None:
        return food, [], []

    extraction, tokens, head = _extraction(tokens, head)
    if extraction:
        notes.insert(0, extraction)

    name, qualifiers, qualifier_notes = _name_and_qualifiers(tokens, head)
    if not name:
        return food, [], []

    return name, qualifiers, qualifier_notes + notes


def _without_filler(tokens):
    """Drop the articles and the filler, and the word in front of a grade number."""
    kept = []
    for i, token in enumerate(tokens):
        word = _plain(token)
        if word in DROP_WORDS:
            continue
        if word in GRADE_MARKERS and i + 1 < len(tokens) and _plain(tokens[i + 1])[:1].isdigit():
            continue
        kept.append(token)
    return kept


def _head_noun(tokens):
    """The last capitalised token that is not the name of a part taken out of something."""
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i][:1].isupper() and _plain(tokens[i]) not in EXTRACTION_NOUNS:
            return i
    return None


def _extraction(tokens, head):
    """Lift 'Saft von' out of the phrase, leaving the product behind as the food.

    Returns ``(note or None, remaining tokens, new head index)``. The note is phrased as the
    line phrased it - 'abgeriebene Schale von' rather than a normalised label - because the
    cook reads it beside the step (owner's ruling, 2026-08-14).
    """
    for i, token in enumerate(tokens):
        if i == head or _plain(token) not in EXTRACTION_NOUNS:
            continue

        # the adjectives standing in front of it belong to the phrase: 'abgeriebene Schale'.
        # Capitalisation says nothing at the head of a line, where the household capitalises
        # the first word whatever it is, so an adjective is recognised by its shape there.
        start = i
        while start - 1 >= 0 and start - 1 != head and _is_adjective(tokens[start - 1]) and _plain(tokens[start - 1]) != 'von':
            start -= 1

        end = i + 1
        if end < len(tokens) and _plain(tokens[end]) == 'von':
            end += 1

        words = [token for token in tokens[start:end] if _plain(token) != 'von']
        phrase = ' '.join(words)
        phrase = phrase[:1].lower() + phrase[1:] if len(words) > 1 else phrase

        remaining = tokens[:start] + tokens[end:]
        return f'{phrase} von', remaining, head - (end - start) if head >= end else head
    return None, tokens, head


def _name_and_qualifiers(tokens, head):
    """Split what is left into the food's name, its qualifiers, and the notes."""
    name_parts, qualifiers, notes = [], [], []

    if _offers_a_choice(tokens[:head]):
        # 'frische oder getrocknete Petersilie' is one food offered two ways, and picking one
        # of them would put a guess on the shopping list. The noun is the food and the whole
        # choice is the note, phrased as the line phrased it.
        return _alias(tokens[head]) + ''.join(f' {t}' for t in tokens[head + 1:]), [], [_choice_note(tokens[:head])]

    for token in tokens[:head]:
        grade = _grade(token)
        if grade is not None:
            qualifiers.append(grade)
            continue
        if BARE_NUMBER.match(token) or not any(character.isalnum() for character in token):
            # an amount the parser could not place - '½ Bund Thymian (…)' leaves the half in
            # the food phrase - or the dash left over from a range it rewrote. Neither a
            # number nor a punctuation mark in front of the noun is ever what you buy.
            continue
        if token[:1].isupper() and not _is_adjective(token):
            # part of a multi-word name rather than a qualifier - 'Rote Bete'
            name_parts.append(token)
            continue
        word = _de_inflect(token)
        first = word.split('/')[0]
        if word in CONDITION_WORDS or (PARTICIPLE.match(first) and first not in PRODUCT_FORMS):
            notes.append(word)
        else:
            qualifiers.append(word)

    # a post-nominal token is already in its citation form and stays exactly as written:
    # 'Paprikapulver edelsüß', 'Crème fraîche', 'Weizenmehl 550' - but a preposition or a
    # conjunction is never part of a name, however it came to be standing there
    trailing = [token for token in tokens[head + 1:] if _plain(token) not in CUT_PREPOSITIONS | CUT_CONJUNCTIONS]
    name = ' '.join(name_parts + [_alias(tokens[head])] + trailing)
    return name, qualifiers, notes


def _is_adjective(token):
    """Is this a qualifier rather than a noun, whatever its capitalisation?

    Lowercase settles it in German. Capitalisation does not, at the head of a line, where the
    household capitalises the first word whatever it is - so a capitalised token counts as a
    qualifier only when its *shape* says so: a participle, or a word the lists already name.
    """
    if token[:1].islower():
        return True
    word = _de_inflect(token)
    return word in CONDITION_WORDS or word in PRODUCT_FORMS or bool(PARTICIPLE.match(word))


def _offers_a_choice(tokens):
    """Do the qualifiers in front of the noun offer a choice - 'frisch oder getrocknet'?"""
    return any(_plain(token) in CUT_CONJUNCTIONS for token in tokens)


def _choice_note(tokens):
    """The choice, phrased as the line phrased it, with a dangling conjunction brought round.

    ``Weizen- oder Dinkelmehl`` names its alternative before the conjunction and its head noun
    after it, so the leftover reads 'Weizen- oder' until the conjunction is moved to the front.
    """
    words = []
    for token in tokens:
        if _plain(token) in CUT_CONJUNCTIONS or _plain(token) in CUT_PREPOSITIONS:
            words.append(_plain(token))
        elif _is_adjective(token):
            words.append(_de_inflect(token))
        else:
            words.append(token)

    if words and _plain(words[-1]) in CUT_CONJUNCTIONS:
        words = [words[-1]] + words[:-1]
    note = ' '.join(words)
    return note[:1].lower() + note[1:]


def _alias(token):
    """The head noun as its food row is spelled: 'Äpfel' -> 'Apfel'."""
    bare = token.strip(EDGE_PUNCTUATION)
    return FOOD_ALIASES.get(bare.lower(), bare)


def _qualified(food, qualifiers):
    """The food name with its qualifiers behind it, each one only once."""
    if not qualifiers:
        return food
    present = {token.lower() for token in food.split()}
    return _joined([food] + [q for q in qualifiers if q.lower() not in present])


def _in_written_order(tokens, line):
    """The phrase back in the order the household wrote it.

    ``IngredientParser`` moves an amount it finds late in a line to the front, so
    ``Saft von 1 Zitrone`` reaches the rule as ``1 Zitrone Saft von`` and the tokens no longer
    stand in the order that says which is the head noun. Reordering is a no-op for every line
    the parser did not shuffle, and is skipped when a token cannot be found in the line at all.
    """
    written = list(enumerate(line.split()))
    taken = set()

    def position(token):
        # each occurrence claims its own place in the line, or a line that says the same word
        # twice collapses them: '130 g Margarine und etwas Margarine zum Fetten der Form'
        # would sort both Margarines to the front and strand the conjunction behind them
        for index, word in written:
            if index not in taken and word == token:
                taken.add(index)
                return index
        # the parser trims as it goes ('1-2' reaches the food phrase as '1-'), so fall back
        # to the first written token this one opens
        for index, word in written:
            if index not in taken and word.startswith(token):
                taken.add(index)
                return index
        return None

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


def _de_inflect(word):
    """'geriebener' -> 'gerieben'. Only ever applied to a lowercase word."""
    lowered = word.strip(EDGE_PUNCTUATION).lower()
    if '/' in lowered:
        # 'gehackte/geschälte' is two words wearing one ending each
        return '/'.join(_de_inflect(part) for part in lowered.split('/') if part)
    if lowered in ADJECTIVE_STEMS:
        return ADJECTIVE_STEMS[lowered]
    if lowered in CONDITION_WORDS or lowered in PRODUCT_FORMS:
        return lowered
    for ending in ADJECTIVE_ENDINGS:
        if lowered.endswith(ending) and len(lowered) - len(ending) >= MINIMUM_STEM:
            stripped = lowered[:-len(ending)]
            # 'geriebene' must not strip past 'gerieben' into 'gerieb', which would be a
            # second spelling of a word the lists already name
            if stripped not in CONDITION_WORDS and stripped not in PRODUCT_FORMS and f'{stripped}en' in PRODUCT_FORMS | CONDITION_WORDS:
                return f'{stripped}en'
            return stripped
    return lowered


def _number(written):
    """'1/2' -> 0.5, '½' -> 0.5, '1,5' -> 1.5."""
    fractions = {'½': 0.5, '¼': 0.25, '¾': 0.75}
    if written in fractions:
        return fractions[written]
    if '/' in written:
        top, _, bottom = written.partition('/')
        return float(top) / float(bottom)
    return float(written.replace(',', '.'))


def _grade(token):
    """'1050er' -> '1050', '4%ige' -> '4%', anything else -> None."""
    match = GRADE.match(token.strip(EDGE_PUNCTUATION))
    return None if not match else match.group(1) + (match.group(2) or '')


def _plain(token):
    return token.strip(EDGE_PUNCTUATION).lower()


def _joined(parts):
    return ' '.join(part.strip() for part in parts if part and part.strip()).strip()
