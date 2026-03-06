from django.contrib import admin

# Register your models here.
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Additional Info", {"fields": ("phone", "role", "created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")
    list_display = ("email", "username", "first_name", "last_name", "role", "is_staff", "is_active")
    search_fields = ("email", "username", "first_name", "last_name")