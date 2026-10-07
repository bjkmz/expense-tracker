from django.db import migrations

CATEGORIES = ['Income', 'Transpo', 'Food', 'Consumable', 'Ownership', 'Miscellaneous']


def seed_categories(apps, schema_editor):
    Category = apps.get_model('tracker', 'Category')
    for name in CATEGORIES:
        Category.objects.get_or_create(name=name)


def unseed_categories(apps, schema_editor):
    Category = apps.get_model('tracker', 'Category')
    Category.objects.filter(name__in=CATEGORIES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('tracker', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed_categories),
    ]
