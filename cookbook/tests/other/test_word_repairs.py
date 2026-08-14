"""Acceptance tests for REQ-007 AC1-AC7 — the Word importer's ingredient repairs.

AC1-AC5 are the rule itself, against ``IngredientParser`` with no database in the way: read
top to bottom they are a specification of what
``cookbook/integration/word_repairs.py`` claims to do. AC6 and AC7 prove the same repairs
survive the trip through the importer and land on ``Ingredient`` rows and on the food tree.

The seam these grade moved on 2026-08-14, after the owner declined the first implementation's
sign-off: Tandoor's shopping list renders the food and never the note, so a qualifier that
decides which item you buy has to be *in the food name*. ``Paprika rot``, not ``Paprika``
noted *rot*. What you do with the thing, and how you judge it at the shelf, is what stays a
note.

What none of them can prove is *yield* over 342 real documents, which is why REQ-007
Decision 10 makes the corpus run a develop-session obligation and AC8 grades the settled
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
    """AC1 — the food is what you buy, named in full; what you do with it is the note."""
    # a colour decides which pepper you pick up, so it is part of the food and not a note.
    # This is the assertion the declined implementation failed: it produced ('Paprika', 'rot')
    # and the shopping list, which renders no notes, said only 'Paprika'.
    assert one('1 rote Paprika') == (1, None, 'Paprika rot', '')

    # the default direction: a qualifier no list in the repair file names stays with the food
    assert one('500 g mageres Hackfleisch') == (500, 'g', 'Hackfleisch mager', '')

    # a past participle names a preparation and is noted - by shape, with no word list
    assert one('1 Zwiebel, gehackt') == (1, None, 'Zwiebel', 'gehackt')

    # ...unless it names something that is sold that way, which PRODUCT_FORMS is for
    assert one('100 g getrocknete Tomaten') == (100, 'g', 'Tomate getrocknet', '')

    # a condition is judged at the shelf or happens in the kitchen; you do not buy ripeness
    assert one('1 reife Avocado') == (1, None, 'Avocado', 'reif')

    # filler says nothing about what to buy, so it is dropped rather than noted
    assert one('Verschiedene Kräuter') == (0, None, 'Kräuter', '')

    # a preposition opens a note of purpose, and the note keeps the words the line used
    assert one('Butter für die Form') == (0, None, 'Butter', 'für die Form')


def test_displaced_units_and_foods_are_recovered():
    """AC2 — the ways the parser displaces something, and all of them back."""
    # the real unit was pushed into the food name; the word that displaced it qualifies the
    # spoon rather than the mustard, so that one *is* a note
    assert one('1 gehäufter Tl Senf') == (1, 'Tl', 'Senf', 'gehäuft')
    assert one('1 gehäufter Teelöffel Salz') == (1, 'Tl', 'Salz', 'gehäuft')

    # the food itself was pushed out of the food slot: the row the parser produces here
    # contains no egg yolk at all, which no amount of adjective handling would fix
    assert one('1 Eigelb zum Bestreichen') == (1, None, 'Eigelb', 'zum Bestreichen')
    assert unrepaired('1 Eigelb zum Bestreichen')[2] == 'zum Bestreichen', ('the fault this criterion is about: the parser keeps the instruction and loses the food')

    # an extraction phrase names a part of something you buy whole, so the whole thing is the
    # food and the part is the note, phrased as the line phrased it (ruled 2026-08-14)
    assert one('Saft von 1 Zitrone') == (1, None, 'Zitrone', 'Saft von')
    assert one('Zitrone, Saft von 1/2') == (0.5, None, 'Zitrone', 'Saft von')
    assert one('Abgeriebene Schale einer Zitrone') == (0, None, 'Zitrone', 'abgeriebene Schale von')

    # the parser transposes an amount it finds late in the line, which moves the noun out of
    # last place - the phrase is put back into written order before the head noun is chosen
    assert one('Mark von 1 Vanilleschote') == (1, None, 'Vanilleschote', 'Mark von')

    # the parser reaches *into* a parenthetical for a quantity and strands the line's own in
    # the food phrase, so this reads as one El of '½ Bund Thymian'. The line's own quantity
    # comes first, and the bracket is put back the way the household wrote it.
    assert one('½ Bund Thymian (es geht auch 1 El getrockneter Thymian)') == (0.5, 'Bund', 'Thymian', 'es geht auch 1 El getrockneter Thymian')
    assert one('½ Pck. Trockenhefe (3,5 g)') == (0.5, 'Päckchen', 'Trockenhefe', '3,5 g')

    # a half is written both ways in this collection, and the parser reads only the digit
    assert one('Saft einer halben Zitrone') == (0.5, None, 'Zitrone', 'Saft von')


def test_grades_conversions_and_keep_whole():
    """AC3 — a grade is data, a cup is a quantity, and some names must not be split."""
    # a grade keeps its number, loses its German suffix, and after the rework it belongs in
    # the food name: it decides which packet you buy (Decision 6)
    assert one('4%ige Natronlauge') == (0, None, 'Natronlauge 4%', '')

    # the collection's three spellings of a flour grade all arrive at one food per grade
    assert one('1050er Weizenmehl') == (0, None, 'Weizenmehl 1050', '')
    assert one('200 g Weizenmehl (550er)') == (200, 'g', 'Weizenmehl 550', '')
    assert one('500 g Weizenmehl Typ 550') == (500, 'g', 'Weizenmehl 550', '')
    assert {one(line)[2] for line in ('200 g Weizenmehl (550er)', '500 g Weizenmehl Typ 550')} == {'Weizenmehl 550'}
    assert all(one(line)[3] == '' for line in ('1050er Weizenmehl', '200 g Weizenmehl (550er)', '500 g Weizenmehl Typ 550')), 'a grade is never left in a note, where the shopping list cannot show it'

    # a household measure that is really a quantity is applied to the amount
    assert one('1 Tasse Milch') == (180, 'ml', 'Milch', '')

    # a name whose first word is not its head noun would be split, or hung under a nonsense
    # parent in the food tree, so keep-whole names it
    assert one('6 Wiener Würstchen') == (6, None, 'Wiener Würstchen', '')
    assert one('200 g Crème fraîche') == (200, 'g', 'Crème fraîche', '')

    # ...but a post-nominal adjective does not inflect in German, so it is kept as written and
    # needs no entry anywhere
    assert one('1 TL Paprikapulver edelsüß') == (1, 'Tl', 'Paprikapulver edelsüß', '')


def test_ranges_and_je_lines_are_fixed_before_parsing():
    """AC4 — the two fixes that change how a line tokenises, so they cannot run after it."""
    # an en dash is not a range to the parser: without this fix the unit is named '–6'
    assert unrepaired('4–6 Eier')[1] == '–6', 'the fault: the range fragment becomes the unit'
    assert one('4–6 Eier') == (4, None, 'Ei', '4 - 6')

    # one written line, two ingredients - which nothing after tokenising could produce. Each
    # colour rides in the food name, because that is where a shopping list can show it.
    assert repaired('Je 1 rote und gelbe Paprika') == [
        (1, None, 'Paprika rot', ''),
        (1, None, 'Paprika gelb', ''),
    ]

    # the collection writes the same shape with three variants too
    assert repaired('Je 1 gelbe, grüne und rote Paprika') == [
        (1, None, 'Paprika gelb', ''),
        (1, None, 'Paprika grün', ''),
        (1, None, 'Paprika rot', ''),
    ]

    # but 'Je' in front of two foods that share only an amount is not that shape, and a
    # variant is always one word: this line stays one ingredient
    assert len(repaired('Je 2 El gemahlene Gewürze und Salz für die Brühe')) == 1


def test_no_repair_loses_a_qualifier():
    """AC5 — nothing the line said may go missing, and a line already right is left alone."""
    unchanged = (
        '375 g Weizenmehl',  # plain: amount, known unit, capitalised food
        '200 g Schafskäse (grob zerbröselt)',  # a parenthetical the parser already noted
        '250 g Zucker',  # a food with no qualifier at all
    )
    for line in unchanged:
        assert one(line) == unrepaired(line), f'{line!r} was already right and must come through untouched'

    # the line the intake prototype failed on. It produced the food 'Braeburn)'; the first
    # implementation produced 'Äpfel' and dropped 'säuerlich' into a note. Both lose something.
    amount, unit, food, note = one('5–6 säuerliche Äpfel (z.B. Braeburn)')
    assert (amount, unit, food, note) == (5, None, 'Apfel säuerlich', '5 - 6 z.B. Braeburn')
    assert ')' not in food and '(' not in food, 'the food never carries a bracket the phrase opened elsewhere'

    # the parser drops this line's parenthetical entirely, so the variety is read back off the
    # line rather than out of the parse. What the household put in brackets is the household
    # speaking, and it survives even when the parser ate it.
    assert 'Braeburn' not in unrepaired('5–6 säuerliche Äpfel (z.B. Braeburn)')[3], 'the fault: the parser keeps nothing of this bracket'

    # a choice between two qualifiers is not a choice the importer gets to make: picking one
    # would put a guess on the shopping list, so the noun is the food and the choice is noted
    assert one('Frische oder getrocknete Petersilie') == (0, None, 'Petersilie', 'frisch oder getrocknet')

    # a choice between two *foods* is different - the first is the food, the rest is the note
    assert one('2 EL Sonnenblumenöl oder Butterschmalz') == (2, 'El', 'Sonnenblumenöl', 'oder Butterschmalz')

    # the general claim, over every line this module names: each qualifying word the source
    # line carried is still somewhere the reader can see it
    for line, qualifiers in (
        ('1 rote Paprika', ('rot',)),
        ('500 g mageres Hackfleisch', ('mager',)),
        ('100 g getrocknete Tomaten', ('getrocknet',)),
        ('1 reife Avocado', ('reif',)),
        ('1050er Weizenmehl', ('1050',)),
        ('5–6 säuerliche Äpfel (z.B. Braeburn)', ('säuerlich',)),
        ('200 g körniger Frischkäse', ('körnig',)),
        ('1 gehäufter Tl Senf', ('gehäuft',)),
    ):
        _, _, food, note = one(line)
        for qualifier in qualifiers:
            assert qualifier in f'{food} {note}', f'{line!r} lost {qualifier!r}: it is in neither the food {food!r} nor the note {note!r}'

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

        assert rows(imported.get(name='Hefezopf')) == [
            ('Weizenmehl 1050', 'g', 500.0, ''),
            ('Milch', 'ml', 180.0, ''),
            ('Salz', 'Tl', 1.0, 'gehäuft'),
            ('Honig flüssig', 'El', 2.0, ''),
            ('Zucker', None, 0.0, ''),
            ('Ei', None, 4.0, '4 - 6'),
            ('Eigelb', None, 1.0, 'zum Bestreichen'),
            ('Weizenmehl 550', 'g', 200.0, ''),
            ('Butter', 'g', 100.0, 'weich'),
            ('Mandel gemahlen', 'g', 200.0, ''),
            ('Zitrone', None, 0.0, 'abgeriebene Schale von'),
        ], 'every section of the repair file, on the Ingredient rows the import created'

        assert rows(imported.get(name='Wurstsalat mit Avocado')) == [
            ('Wiener Würstchen', None, 6.0, ''),
            ('Avocado', None, 2.0, 'reif'),
            ('Avocado', None, 1.0, ''),
            ('Olivenöl', 'El', 3.0, ''),
            ('Paprika rot', None, 1.0, ''),
            ('Paprika gelb', None, 1.0, ''),
            ('Tomate', 'Dose', 1.0, 'gehackt'),
            ('Tomate', None, 2.0, ''),
            ('Limette', None, 0.0, 'Saft von'),
            ('Käse gerieben', 'g', 200.0, ''),
            ('Frischkäse körnig', 'g', 200.0, ''),
            ('Paprikapulver edelsüß', 'Tl', 1.0, ''),
            ('Petersilie', None, 0.0, 'frisch oder getrocknet'),
            ('Öl', None, 0.0, 'für die Form'),
        ], 'one line became two ingredients, and the qualifiers ride in the food names'

        # the point of all of it: two spellings of one thing are one row, not two
        assert Food.objects.filter(space=space, name__in=('Avocado', 'Avocados')).count() == 1
        assert Food.objects.filter(space=space, name__in=('Tomate', 'Tomaten')).count() == 1
        assert Unit.objects.filter(space=space, name__in=('El', 'EL', 'Esslöffel')).count() == 1

        # and no unit exists that the repair file does not call a unit - the check that fails
        # if the rule silently stops firing on a line shape nobody wrote a test for
        created = {unit.name for unit in Unit.objects.filter(space=space)}
        assert created <= set(KNOWN_UNITS.values()), f'the import invented units the repair file does not name: {sorted(created - set(KNOWN_UNITS.values()))}'


def test_the_food_tree_is_built(u1_s1):
    """AC7 — the qualified foods hang under their head noun, and the parent substitutes.

    Naming a food in full is what makes the shopping list useful and what multiplies the food
    list. The tree is the other half of that trade (Decision 16): it does not merge shopping
    rows - nothing in ``shopping_helper`` looks at descendants - but it lets one flour stand in
    for another in the make-now filter, and it puts the shop aisle in one place.
    """
    space, request = request_generator(u1_s1)

    with scope(space=space):
        integration = get_integration(request, ImportExportBase.WORD)
        il = ImportLog.objects.create(type=ImportExportBase.WORD, created_by=request.user, space=space)

        integration.do_import([{'file': build_zip(), 'name': 'Rezepte.zip'}], il, False)

        def food(name):
            return Food.objects.get(space=space, name=name)

        # a parent is created even though no line in either document names the bare noun
        for parent_name, children in (('Weizenmehl', {'Weizenmehl 1050', 'Weizenmehl 550'}), ('Paprika', {'Paprika rot', 'Paprika gelb'})):
            parent = food(parent_name)
            assert {child.name for child in parent.get_children()} == children, f'{parent_name} did not gather its qualified foods'
            assert parent.is_root(), f'{parent_name} is the head noun and belongs at the root'
            assert parent.substitute_children, f'{parent_name} must substitute its children, or the tree buys nothing'
            for child in parent.get_children():
                assert child.get_parent().pk == parent.pk

        # a name whose second token is capitalised is a name, not a noun plus its qualifiers
        assert food('Wiener Würstchen').is_root()
        assert not Food.objects.filter(space=space, name='Wiener').exists(), 'a name must not invent a parent out of its own first word'

        # nothing about the tree changed what the ingredient rows point at
        for recipe in Recipe.objects.filter(keywords=integration.keyword):
            for name, _, _, _ in rows(recipe):
                assert Food.objects.filter(space=space, name=name).exists()


def rows(recipe):
    """Every ingredient row of a recipe, in the order the document wrote them."""
    return [(i.food.name, i.unit.name if i.unit else None, float(i.amount), i.note) for step in recipe.steps.all().order_by('order')
            for i in step.ingredients.all().order_by('pk')]
