"""Acceptance tests for REQ-007 AC1-AC6 — the Word importer's ingredient repairs.

AC1-AC5 are the rule itself, against ``IngredientParser`` with no database in the way: read
top to bottom they are a specification of what
``cookbook/integration/word_repairs.py`` claims to do. AC6 proves the same repairs survive the
trip through the importer and land on ``Ingredient`` rows.

What none of them can prove is *yield* over 342 real documents, which is why REQ-007
Decision 10 makes the corpus run a develop-session obligation and AC7 grades the settled
result on the deployed instance. No document from the household collection is committed and no
real ingredient line is asserted against here; every line below is written for the test, to the
collection's conventions.
"""
import os
from io import BytesIO
from zipfile import ZipFile

from django.contrib import auth
from django.test import RequestFactory
from django_scopes import scope

from cookbook.forms import ImportExportBase
from cookbook.helper.ingredient_parser import IngredientParser
from cookbook.integration.word_repairs import KNOWN_UNITS, prepare_line, repair
from cookbook.models import Food, ImportLog, Recipe, Unit
from cookbook.views.import_export import get_integration

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_data', 'Word')

#: the two REQ-007 fixture documents, in the folder layout the importer reads categories from
ZIP_LAYOUT = (
    ('Kuchen/repairs_hefezopf.docx', 'repairs_hefezopf.docx'),
    ('Salate/repairs_wurstsalat.docx', 'repairs_wurstsalat.docx'),
)

parser = IngredientParser(None, cache_mode=False, ignore_automations=True)


def repaired(line):
    """Every ingredient one written line yields, as ``(amount, unit, food, note)``."""
    return [repair(prepared, *parser.parse(prepared)) for prepared in prepare_line(line)]


def one(line):
    """The single ingredient a line yields, for the lines that yield exactly one."""
    results = repaired(line)
    assert len(results) == 1, f'{line!r} was expected to yield one ingredient, not {len(results)}'
    return results[0]


def unrepaired(line):
    """What Tandoor's own parser makes of the line, with no repair applied at all."""
    return parser.parse(line)


def fixture_bytes(name):
    with open(os.path.join(FIXTURES, name), 'rb') as f:
        return f.read()


def build_zip():
    stream = BytesIO()
    with ZipFile(stream, 'w') as archive:
        for path, source in ZIP_LAYOUT:
            archive.writestr(path, fixture_bytes(source))
    stream.seek(0)
    stream.name = 'Rezepte.zip'
    return stream


def request_generator(u1_s1):
    user = auth.get_user(u1_s1)
    space = user.userspace_set.first().space
    request = RequestFactory()
    request.user = user
    request.space = space
    return space, request


def test_the_food_is_the_thing_you_buy():
    """AC1 — the rule the owner's rulings turned out to share, on the rulings themselves."""
    # the adjective in the unit slot is not a unit; the food was right all along
    assert one('1 reife Avocado') == (1, None, 'Avocado', 'reif')

    # the adjective in front of the food is not part of what you buy
    assert one('200 g geriebener Käse') == (200, 'g', 'Käse', 'gerieben')

    # the last capitalised noun wins over the part of it the line names
    assert one('Saft einer Limette') == (0, None, 'Limette', 'Saft')

    # ... and it wins with no list naming 'flüssig' anywhere: capitalisation is the rule
    assert one('flüssiger Honig') == (0, None, 'Honig', 'flüssig')

    # filler says nothing about what to buy, so it is dropped rather than noted
    assert one('Verschiedene Kräuter') == (0, None, 'Kräuter', '')

    # a preposition opens a note, and the note keeps the words the line used
    assert one('Butter für die Form') == (0, None, 'Butter', 'für die Form')


def test_displaced_units_and_foods_are_recovered():
    """AC2 — the two ways the parser displaces something, and both directions back."""
    # the real unit was pushed into the food name; the adjective that displaced it is a note
    assert one('1 gehäufter Tl Senf') == (1, 'Tl', 'Senf', 'gehäuft')

    # the food itself was pushed out of the food slot: the row the parser produces here
    # contains no egg yolk at all, which no amount of adjective handling would fix
    assert one('1 Eigelb zum Bestreichen') == (1, None, 'Eigelb', 'zum Bestreichen')
    assert unrepaired('1 Eigelb zum Bestreichen')[2] == 'zum Bestreichen', ('the fault this criterion is about: the parser keeps the instruction and loses the food')


def test_grades_conversions_and_keep_whole():
    """AC3 — a grade is data, a cup is a quantity, and some names must not be split."""
    # a grade keeps its number and loses its German suffix, whether it stands in the food
    # phrase or in a note the parser wrote (the owner's ruling of 2026-08-14)
    assert one('4%ige Natronlauge') == (0, None, 'Natronlauge', '4%')
    assert one('1050er Weizenmehl') == (0, None, 'Weizenmehl', '1050')
    assert one('200 g Weizenmehl (550er)') == (200, 'g', 'Weizenmehl', '550')

    # which is what makes the collection's three spellings of the same flour one food, with
    # one note: 'Weizenmehl · 550' says what 'Weizenmehl · Typ 550' says (ruled 2026-08-14)
    assert one('500 g Weizenmehl Typ 550') == (500, 'g', 'Weizenmehl', '550')
    assert {one(line)[2] for line in ('1050er Weizenmehl', '200 g Weizenmehl (550er)', '500 g Weizenmehl Typ 550')} == {'Weizenmehl'}
    assert one('200 g Weizenmehl (550er)')[3] == one('500 g Weizenmehl Typ 550')[3] == '550'

    # a household measure that is really a quantity is applied to the amount
    assert one('1 Tasse Milch') == (180, 'ml', 'Milch', '')

    # a genuine multi-word name survives the rule that would otherwise split it
    assert one('6 Wiener Würstchen') == (6, None, 'Wiener Würstchen', '')

    # and the rule leaves a lowercase second word alone on its own, so this needs no entry
    assert 'crème fraîche' not in {name.lower() for name in KNOWN_UNITS}
    assert one('Crème fraîche') == (0, None, 'Crème fraîche', '')
    assert one('Crème fraîche') == unrepaired('Crème fraîche'), 'nothing in the repair file names it'


def test_ranges_and_je_lines_are_fixed_before_parsing():
    """AC4 — the two fixes that change how a line tokenises, so they cannot run after it."""
    # an en dash is not a range to the parser: without this fix the unit is named '–6'
    assert unrepaired('4–6 Eier')[1] == '–6', 'the fault: the range fragment becomes the unit'
    assert one('4–6 Eier') == (4, None, 'Ei', '4 - 6')

    # one written line, two ingredients - which nothing after tokenising could produce
    assert repaired('Je 1 rote und gelbe Paprika') == [
        (1, None, 'Paprika', 'rot'),
        (1, None, 'Paprika', 'gelb'),
    ]

    # the collection writes the same shape with three variants too
    assert repaired('Je 1 gelbe, grüne und rote Paprika') == [
        (1, None, 'Paprika', 'gelb'),
        (1, None, 'Paprika', 'grün'),
        (1, None, 'Paprika', 'rot'),
    ]

    # but 'Je' in front of two foods that share only an amount is not that shape, and a
    # variant is always one word: this line stays one ingredient
    assert len(repaired('Je 2 El gemahlene Gewürze und Salz für die Brühe')) == 1


def test_a_repair_never_makes_a_line_worse():
    """AC5 — leaving a line alone is always available, and is what happens when in doubt."""
    unchanged = (
        '375 g Weizenmehl',  # plain: amount, known unit, capitalised food
        '200 g Schafskäse (grob zerbröselt)',  # an adjective no list names, in a note
        '1 - 2 El Zitronensaft (frisch gepresst)',  # a parenthetical note and a range together
    )
    for line in unchanged:
        assert one(line) == unrepaired(line), f'{line!r} was already right and must come through untouched'

    # the one deliberate exception, ruled by the owner on 2026-08-14: a grade in a note the
    # parser wrote is reduced to its number. Nothing else about the line moves.
    amount, unit, food, note = one('375 g Weizenmehl (550er)')
    assert (amount, unit, food) == unrepaired('375 g Weizenmehl (550er)')[:3]
    assert (note, unrepaired('375 g Weizenmehl (550er)')[3]) == ('550', '550er')

    # the line the intake prototype failed on: a range and a parenthetical, where re-cutting
    # the food phrase produced the food 'Braeburn)'
    amount, unit, food, note = one('5–6 säuerliche Äpfel (z.B. Braeburn)')
    assert food == 'Äpfel', 'the food is the apples, not the variety the note suggests'
    assert ')' not in food and '(' not in food, 'the food never carries a bracket the phrase opened elsewhere'
    assert unit is None, 'the range fragment the parser called a unit is not a unit'
    assert (amount, '–6' in note) == (5, True), 'the range the parser called a unit survives as a note'

    # the parser drops this line's parenthetical entirely, before any repair sees it. That
    # loss is not this rule's to undo - recovering it would mean rewriting a note the parser
    # wrote, which is the one thing the unchanged set above exists to forbid.
    assert 'Braeburn' not in unrepaired('5–6 säuerliche Äpfel (z.B. Braeburn)')[3]

    # a bracket left without its partner is not part of a food name
    assert one('(viel Dill)')[2] == 'Dill'


def test_zip_import_applies_every_repair(u1_s1):
    """AC6 — the repairs survive the trip through the importer and land on the rows."""
    space, request = request_generator(u1_s1)

    with scope(space=space):
        integration = get_integration(request, ImportExportBase.WORD)
        il = ImportLog.objects.create(type=ImportExportBase.WORD, created_by=request.user, space=space)

        integration.do_import([{'file': build_zip(), 'name': 'Rezepte.zip'}], il, False)

        imported = Recipe.objects.filter(keywords=integration.keyword)
        assert {r.name for r in imported} == {'Hefezopf', 'Wurstsalat mit Avocado'}

        def rows(recipe):
            return [(i.food.name, i.unit.name if i.unit else None, float(i.amount), i.note) for step in recipe.steps.all().order_by('order')
                    for i in step.ingredients.all().order_by('pk')]

        assert rows(imported.get(name='Hefezopf')) == [
            ('Weizenmehl', 'g', 500.0, '1050'),
            ('Milch', 'ml', 180.0, ''),
            ('Salz', 'Tl', 1.0, 'gehäuft'),
            ('Honig', 'El', 2.0, 'flüssig'),
            ('Zucker', None, 0.0, ''),
            ('Ei', None, 4.0, '4 - 6'),
            ('Eigelb', None, 1.0, 'zum Bestreichen'),
            ('Weizenmehl', 'g', 200.0, '550'),
        ], 'every section of the repair file, on the Ingredient rows the import created'

        assert rows(imported.get(name='Wurstsalat mit Avocado')) == [
            ('Wiener Würstchen', None, 6.0, ''),
            ('Avocado', None, 2.0, 'reif'),
            ('Avocado', None, 1.0, ''),
            ('Olivenöl', 'El', 3.0, ''),
            ('Paprika', None, 1.0, 'rot'),
            ('Paprika', None, 1.0, 'gelb'),
            ('Tomate', 'Dose', 1.0, 'gehackt'),
            ('Tomate', None, 2.0, ''),
            ('Limette', None, 0.0, 'Saft'),
            ('Käse', 'g', 200.0, 'gerieben'),
            ('Öl', None, 0.0, 'für die Form'),
        ], 'one line became two ingredients, and the rest carry their notes'

        # the point of all of it: two spellings of one thing are one row, not two
        assert Food.objects.filter(space=space, name__in=('Avocado', 'Avocados')).count() == 1
        assert Food.objects.filter(space=space, name__in=('Tomate', 'Tomaten')).count() == 1
        assert Unit.objects.filter(space=space, name__in=('El', 'EL', 'Esslöffel')).count() == 1

        # and no unit exists that the repair file does not call a unit - the check that fails
        # if the rule silently stops firing on a line shape nobody wrote a test for
        created = {unit.name for unit in Unit.objects.filter(space=space)}
        assert created <= set(KNOWN_UNITS.values()), f'the import invented units the repair file does not name: {sorted(created - set(KNOWN_UNITS.values()))}'
