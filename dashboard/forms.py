from django import forms
from django.utils import timezone
from .models import Client, Prospect, Facture, LigneFacture


class StyledFormMixin:
    """Ajoute les classes CSS du design system aux widgets."""

    WIDGET_CLASSES = {
        forms.TextInput: 'form-input',
        forms.EmailInput: 'form-input',
        forms.NumberInput: 'form-input',
        forms.URLInput: 'form-input',
        forms.PasswordInput: 'form-input',
        forms.DateInput: 'form-input',
        forms.DateTimeInput: 'form-input',
        forms.Textarea: 'form-textarea',
        forms.Select: 'form-select',
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
            'notes': forms.Textarea(attrs={'rows': 3}),
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Le champ source n'est pas destiné à être saisi côté UI
        self.fields['source_recurring'].widget = forms.HiddenInput()
        self.fields['source_recurring'].required = False
        # Prochaine génération est calculée côté backend
        self.fields['recurrence_prochaine'].disabled = True
        self.fields['recurrence_prochaine'].required = False
        # Montant HT est calculé à partir des lignes côté front + recalcul backend
        self.fields['montant_ht'].widget.attrs.setdefault('readonly', True)
        # Valeur par défaut : échéance = date d'émission (modifiable par l'utilisateur)
        if not self.is_bound and not getattr(self.instance, "pk", None):
            emission = self.initial.get('date_emission') or timezone.now().date()
            self.initial.setdefault('date_emission', emission)
            self.initial.setdefault('date_echeance', emission)

    def clean_source_recurring(self):
        val = self.cleaned_data.get('source_recurring')
        return val or None

    class Meta:
        model = Facture
        fields = [
            'client', 'objet', 'montant_ht', 'tva_rate',
            'statut', 'date_emission', 'date_echeance', 'notes',
            'type_facture', 'recurrence_frequence', 'recurrence_debut',
            'recurrence_fin', 'recurrence_prochaine', 'recurrence_active',
            'source_recurring',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
            'date_emission': forms.DateInput(attrs={'type': 'date'}),
            'date_echeance': forms.DateInput(attrs={'type': 'date'}),
            'recurrence_debut': forms.DateInput(attrs={'type': 'date'}),
            'recurrence_fin': forms.DateInput(attrs={'type': 'date'}),
            'recurrence_prochaine': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'client': 'Client',
            'objet': 'Objet / Libellé',
            'montant_ht': 'Montant HT (DH)',
            'tva_rate': 'Taux TVA (%)',
            'statut': 'Statut',
            'date_emission': "Date d'émission",
            'date_echeance': "Date d'échéance",
            'notes': 'Notes',
            'type_facture': 'Type de facture',
            'recurrence_frequence': 'Fréquence de récurrence',
            'recurrence_debut': 'Date de début',
            'recurrence_fin': 'Date de fin (optionnelle)',
            'recurrence_prochaine': 'Prochaine génération',
            'recurrence_active': 'Récurrence active',
            'source_recurring': 'Facture source',
        }


class LigneFactureForm(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Préremplit le type de ligne par défaut
        if not self.initial.get('item_type'):
            self.initial['item_type'] = 'NORMAL'
        self.fields['item_type'].initial = self.initial.get('item_type', 'NORMAL')
        # Quantité par défaut = 1
        if not self.initial.get('quantite'):
            self.fields['quantite'].initial = 1

    class Meta:
        model = LigneFacture
        fields = ['description', 'quantite', 'prix_unitaire', 'item_type']
        labels = {
            'description': 'Description',
            'quantite': 'Qté',
            'prix_unitaire': 'P.U. HT (DH)',
            'item_type': 'Type de ligne',
        }
        widgets = {
            'item_type': forms.HiddenInput(),
        }


LigneFactureFormSet = forms.inlineformset_factory(
    Facture,
    LigneFacture,
    form=LigneFactureForm,
    extra=1,
    can_delete=True,
    min_num=0,
)
