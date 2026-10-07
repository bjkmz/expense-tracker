from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('partials/calendar-day/', views.calendar_day, name='calendar-day-stub'),
    path('partials/calendar/day/', views.calendar_day, name='calendar-day'),
    path('partials/calendar/month/', views.calendar_month, name='calendar-month'),
    path('day/<slug:iso>/', views.day_detail, name='day-detail'),
    path('month/<slug:ym>/', views.month_detail, name='month-detail'),
    # Records panel partials (HTMX refresh targets)
    path('partials/records/day/', views.records_panel_day, name='records-panel-day'),
    path('partials/records/month/', views.records_panel_month, name='records-panel-month'),
    # Record mutations: POST-only (HTMX-friendly; avoids Django PUT parsing)
    path('records/', views.record_create, name='record-create'),
    path('records/<int:pk>/', views.record_update, name='record-update'),
    path('records/<int:pk>/move/', views.record_move, name='record-move'),
    path('records/<int:pk>/delete/', views.record_delete, name='record-delete'),
    # Insights partials (HTMX toggle/sort targets)
    path('partials/insights/chart/', views.insights_chart, name='insights-chart'),
    path('partials/insights/list/', views.insights_list, name='insights-list'),
]
