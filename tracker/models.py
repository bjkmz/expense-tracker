from django.db import models

EXPENSE_CATEGORIES = ('Transpo', 'Food', 'Consumable', 'Ownership', 'Miscellaneous')


class Category(models.Model):
    name = models.CharField(max_length=32, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name

    @property
    def is_income(self) -> bool:
        return self.name == 'Income'


class Expense(models.Model):
    item = models.CharField(max_length=128)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='expenses')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['date', 'updated_at']),
            models.Index(fields=['category', 'date']),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f'{self.item} {self.amount} on {self.date}'
