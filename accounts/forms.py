from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from .models import UserRole


class StyledFormMixin:
    """Add Tailwind utility classes to widgets to match the design system."""

    WIDGET_CLASSES = {
        forms.TextInput: "form-input",
        forms.EmailInput: "form-input",
        forms.NumberInput: "form-input",
        forms.URLInput: "form-input",
        forms.PasswordInput: "form-input",
        forms.DateInput: "form-input",
        forms.DateTimeInput: "form-input",
        forms.Textarea: "form-textarea",
        forms.Select: "form-select",
        forms.SelectMultiple: "form-select",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = self.WIDGET_CLASSES.get(type(field.widget))
            if css:
                field.widget.attrs.setdefault("class", css)


class EmployeeCreateForm(StyledFormMixin, forms.ModelForm):
    password1 = forms.CharField(
        label="Mot de passe",
        strip=False,
        widget=forms.PasswordInput,
    )
    password2 = forms.CharField(
        label="Confirmer le mot de passe",
        strip=False,
        widget=forms.PasswordInput,
    )

    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "email", "role"]
        labels = {
            "first_name": "Prénom",
            "last_name": "Nom",
            "email": "Email",
            "role": "Rôle",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_roles = [
            (UserRole.RECOVEREMENT, "Recouvrement"),
            (UserRole.MARKETING, "Marketing"),
        ]
        self.fields["role"].choices = allowed_roles
        self.allowed_role_values = {choice[0] for choice in allowed_roles}

    def clean_role(self):
        role = self.cleaned_data.get("role")
        if role not in self.allowed_role_values:
            raise forms.ValidationError("Rôle non autorisé pour cet écran.")
        return role

    def clean(self):
        cleaned = super().clean()
        pwd1 = cleaned.get("password1")
        pwd2 = cleaned.get("password2")
        if pwd1 and pwd2 and pwd1 != pwd2:
            self.add_error("password2", "Les mots de passe ne correspondent pas.")
        if pwd1:
            validate_password(pwd1, user=None)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        # Re-use the email as username to satisfy the AbstractUser constraint.
        user.username = user.email
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user
