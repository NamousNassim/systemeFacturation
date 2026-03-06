from django import forms
from .models import Client, Prospect, Facture, LigneFacture


class StyledFormMixin:
    """Add design-system CSS classes to all form widgets automatically."""

    WIDGET_CLASSES = {
        forms.TextInput:      'form-input',
        forms.EmailInput:     'form-input',
        forms.NumberInput:    'form-input',
        forms.URLInput:       'form-input',
        forms.PasswordInput:  'form-input',
        forms.DateInput:      'form-input',
        forms.DateTimeInput:  'form-input',
        forms.Textarea:       'form-textarea',
        forms.Select:         'form-select',
        forms.SelectMultiple: 'form-select',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = self.WIDGET_CLASSES.get(type(field.widget))
            if css:
                field.widget.attrs.setdefault('class', css)


class ClientForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Client
        fields = [
            'nom', 'prenom', 'email', 'telephone',
            'societe', 'adresse', 'siret', 'statut', 'notes',
        ]
        widgets = {
            'adresse': forms.Textarea(attrs={'rows': 2}),
            'notes':   forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'nom': 'Nom',
            'prenom': 'Prénom',
            'email': 'Email',
            'telephone': 'Téléphone',
            'societe': 'Société',
            'adresse': 'Adresse',
            'siret': 'RC',
            'statut': 'Statut',
            'notes': 'Notes internes',
        }


class ProspectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Prospect
        fields = [
            'nom', 'prenom', 'email', 'telephone',
            'societe', 'statut', 'source', 'notes', 'date_dernier_contact',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'date_dernier_contact': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'nom': 'Nom',
            'prenom': 'Prénom',
            'email': 'Email',
            'telephone': 'Téléphone',
            'societe': 'Société',
            'statut': 'Statut pipeline',
            'source': 'Source',
            'notes': 'Notes internes',
            'date_dernier_contact': 'Dernier contact',
        }


class FactureForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Facture
        fields = [
            'client', 'objet', 'montant_ht', 'taux_tva',
            'statut', 'date_emission', 'date_echeance', 'notes',
        ]
        widgets = {
            'notes':          forms.Textarea(attrs={'rows': 2}),
            'date_emission':  forms.DateInput(attrs={'type': 'date'}),
            'date_echeance':  forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'client':         'Client',
            'objet':          'Objet / Libellé',
            'montant_ht':     'Montant HT (DH)',
            'taux_tva':       'Taux TVA (%)',
            'statut':         'Statut',
            'date_emission':  "Date d'émission",
            'date_echeance':  "Date d'échéance",
            'notes':          'Notes',
        }


class LigneFactureForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LigneFacture
        fields = ['description', 'quantite', 'prix_unitaire']
        labels = {
            'description':   'Description',
            'quantite':      'Qté',
            'prix_unitaire': 'P.U. HT (DH)',
        }


LigneFactureFormSet = forms.inlineformset_factory(
    Facture,
    LigneFacture,
    form=LigneFactureForm,
    extra=3,
    can_delete=True,
    min_num=0,
)
