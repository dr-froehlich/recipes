import os
import traceback
from io import BytesIO
from zipfile import BadZipFile

from django.utils.translation import gettext as _
from django_scopes import scope

from cookbook.helper.ingredient_parser import IngredientParser
from cookbook.helper.word_parser import WordDocumentSkipped, parse_docx
from cookbook.integration.integration import Integration
from cookbook.integration.word_repairs import prepare_line, repair
from cookbook.models import Ingredient, Keyword, Recipe, Step


class Word(Integration):
    """Import recipes written as Word documents (REQ-006).

    Accepts a single ``.docx`` or a ``.zip`` of many. The document conventions live in
    ``cookbook/helper/word_parser.py``; this class only maps what it returns onto models,
    with ingredient lines handed to the same ``IngredientParser`` the rest of Tandoor uses.

    ``do_import`` is overridden rather than inherited because the base method reads a zip
    entry and passes the bytes on without its path, and the path is what names the category
    keyword. Recovering it afterwards - by iteration order, or by hashing content - would
    fail silently rather than loudly when it failed, which is the one outcome a category
    keyword must not have.
    """

    def import_file_name_filter(self, zip_info_object):
        filename = zip_info_object.filename
        if not filename.lower().endswith('.docx'):
            return False
        # Word's lock files, and the folder a macOS zip carries its metadata in
        return not os.path.basename(filename).startswith('~$') and not filename.startswith('__MACOSX/')

    def get_recipe_from_file(self, file):
        path = getattr(file, 'name', '') or ''
        return self.create_recipe(parse_docx(file.read(), fallback_name=self.document_name(path)), path)

    def do_import(self, files, il, import_duplicates, meal_plans=True, shopping_lists=True, nutrition_per_serving=False):
        with scope(space=self.request.space):
            self.import_log = il
            self.import_duplicates = import_duplicates
            self.files = files

            try:
                documents = []
                for f in files:
                    if f['name'].lower().endswith('.zip'):
                        documents += self.documents_from_zip(f['file'])
                    else:
                        documents.append((f['name'], f['file'].read()))

                il.total_recipes += len(documents)
                il.save()

                for path, data in documents:
                    self.import_document(path, data, il, import_duplicates)
            except BadZipFile:
                il.msg += 'ERROR ' + _('Importer expected a .zip file. Did you choose the correct importer type for your data ?') + '\n'
            except Exception as e:
                msg = 'ERROR ' + _('An unexpected error occurred during the import. Please make sure you have uploaded a valid file.') + '\n' + str(e) + '\n'
                self.handle_exception(e, log=il, message=msg)

            if len(self.ignored_recipes) > 0:
                il.msg += '\n' + _('The following recipes were ignored because they already existed:') + ' ' + ', '.join(self.ignored_recipes) + '\n\n'

            il.keyword = self.keyword
            il.msg += (_('Imported %s recipes.') % Recipe.objects.filter(keywords=self.keyword).count()) + '\n'
            il.running = False
            il.save()

    def documents_from_zip(self, file):
        """Every .docx in the archive as ``(path, bytes)``, paths relative to the collection."""
        import_zip = self.get_zip_file(file)
        entries = [z for z in import_zip.filelist if self.import_file_name_filter(z)]
        documents = list(zip(self.strip_common_root([z.filename for z in entries]), (self.safe_read(import_zip, z) for z in entries)))
        import_zip.close()
        return documents

    @staticmethod
    def strip_common_root(paths):
        """Drop leading directories every entry shares.

        Zipping the collection folder itself would otherwise put all 300 recipes under one
        useless keyword named after that folder.
        """
        while len(paths) > 1:
            roots = {path.split('/')[0] for path in paths if '/' in path}
            if len(roots) != 1 or any('/' not in path for path in paths):
                break
            prefix = len(roots.pop()) + 1
            paths = [path[prefix:] for path in paths]
        return paths

    @staticmethod
    def top_level_folder(path):
        """The category a document sat in: the first path segment, deeper ones ignored.

        Ignoring the deeper segments is what collapses the collection's print subfolders
        (Decision 8) without this fork knowing a single one of their names.
        """
        return path.split('/')[0] if '/' in path else ''

    @staticmethod
    def document_name(path):
        return os.path.splitext(os.path.basename(path))[0]

    def import_document(self, path, data, il, import_duplicates):
        """Import one document, or say in the log why it was not. Never aborts the run."""
        try:
            parsed = parse_docx(data, fallback_name=self.document_name(path))
        except WordDocumentSkipped as e:
            il.msg += f'SKIPPED {path}: {e.reason}\n'
            il.save()
            return
        except Exception as e:
            traceback.print_exc()
            self.handle_exception(e, log=il, message=f'-------------------- \nERROR IMPORTING {path}\n{e}\n--------------------\n')
            return

        try:
            recipe = self.create_recipe(parsed, path)
            recipe.keywords.add(self.keyword)
            il.msg += self.get_recipe_processed_msg(recipe)
            self.handle_duplicates(recipe, import_duplicates)
            il.imported_recipes += 1
            il.save()
        except Exception as e:
            traceback.print_exc()
            self.handle_exception(e, log=il, message=f'-------------------- \nERROR IMPORTING {path}\n{e}\n--------------------\n')

    def create_recipe(self, parsed, path):
        recipe = Recipe.objects.create(
            name=parsed.name[:Recipe._meta.get_field('name').max_length],
            servings=parsed.servings,
            servings_text=parsed.servings_text[:Recipe._meta.get_field('servings_text').max_length],
            created_by=self.request.user,
            internal=True,
            space=self.request.space,
        )

        ingredient_parser = IngredientParser(self.request, True)
        step_name_length = Step._meta.get_field('name').max_length
        order = 0

        for component in parsed.components:
            # a component with ingredients but no method still needs one step to hang them on
            instructions = component.instructions or ['']
            first_step = None

            for instruction in instructions:
                step = Step.objects.create(
                    name=component.name[:step_name_length] if first_step is None else '',
                    instruction=instruction,
                    order=order,
                    space=self.request.space,
                    show_ingredients_table=self.request.user.userpreference.show_step_ingredients,
                )
                recipe.steps.add(step)
                first_step = first_step or step
                order += 1

            for line in component.ingredients:
                # REQ-007: the household writes German, where the token after the amount is
                # usually an adjective rather than a unit. prepare_line runs before parsing
                # because its two fixes change how the line tokenises; repair runs after it,
                # where what the parser made of each token is known rather than guessed.
                for prepared in prepare_line(line):
                    amount, unit, food, note = repair(prepared, *ingredient_parser.parse(prepared))
                    first_step.ingredients.add(
                        Ingredient.objects.create(
                            food=ingredient_parser.get_food(food),
                            unit=ingredient_parser.get_unit(unit),
                            amount=amount,
                            note=note,
                            original_text=prepared,
                            space=self.request.space,
                        )
                    )

        folder = self.top_level_folder(path)
        if folder:
            keyword, created = Keyword.objects.get_or_create(name=folder[:Keyword._meta.get_field('name').max_length], space=self.request.space)
            recipe.keywords.add(keyword)

        if parsed.image:
            try:
                self.import_recipe_image(recipe, BytesIO(parsed.image), filetype=parsed.image_filetype)
            except Exception as e:
                # a picture Pillow cannot read costs the picture, not the recipe
                self.handle_exception(e, log=self.import_log, message=f'IMAGE SKIPPED {path}: {e}\n')

        recipe.save()
        return recipe
