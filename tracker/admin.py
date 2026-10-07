from django.contrib import admin

from .models import Category, Expense


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('id', 'item', 'category', 'amount', 'date', 'updated_at')
    list_filter = ('category', 'date')
    search_fields = ('item',)
    date_hierarchy = 'date'
