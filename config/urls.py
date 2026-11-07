"""URL-конфигурация проекта FIPLPEOPLE.RU.

Клиентская часть и публичные страницы не входят в текущую задачу:
маршруты появятся на следующих этапах. Сейчас доступна только
административная панель Django.
"""

from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
