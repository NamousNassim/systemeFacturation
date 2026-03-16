from decimal import Decimal, ROUND_HALF_UP
from datetime import date

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError


# ── CLIENT ──────────────────────────────────────────────────────────────────

class ClientStatut(models.TextChoices):
    ACTIF   = 'ACTIF',   'Actif'
    INACTIF = 'INACTIF', 'Inactif'


class Client(models.Model):
    nom        = models.CharField(max_length=100, verbose_name='Nom')
    prenom     = models.CharField(max_length=100, blank=True, verbose_name='Prénom')
    email      = models.EmailField(blank=True, verbose_name='Email')
    telephone  = models.CharField(max_length=20, blank=True, verbose_name='Téléphone')
    societe    = models.CharField(max_length=200, blank=True, verbose_name='Société')
    adresse    = models.TextField(blank=True, verbose_name='Adresse')
    siret      = models.CharField(max_length=20, blank=True, verbose_name='RC')
    statut     = models.CharField(
        max_length=10, choices=ClientStatut.choices, default=ClientStatut.ACTIF,
        verbose_name='Statut'
    )
    notes      = models.TextField(blank=True, verbose_name='Notes')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='clients_crees',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Client'
        verbose_name_plural = 'Clients'

    def __str__(self):
        if self.societe:
            return f"{self.societe} — {self.nom} {self.prenom}".strip()
        return f"{self.nom} {self.prenom}".strip()


# ── PROSPECT ────────────────────────────────────────────────────────────────

class ProspectStatut(models.TextChoices):
    NOUVEAU        = 'NOUVEAU',        'Nouveau'
    CONTACTE       = 'CONTACTE',       'Contacté'
    EN_NEGOCIATION = 'EN_NEGOCIATION', 'En négociation'
    GAGNE          = 'GAGNE',          'Gagné'
    PERDU          = 'PERDU',          'Perdu'


class ProspectSource(models.TextChoices):
    REFERRAL      = 'REFERRAL',      'Référence'
    EMAIL         = 'EMAIL',         'Email'
    RESEAU_SOCIAL = 'RESEAU_SOCIAL', 'Réseau social'
    SITE_WEB      = 'SITE_WEB',      'Site web'
    EVENEMENT     = 'EVENEMENT',     'Événement'
    AUTRE         = 'AUTRE',         'Autre'


class Prospect(models.Model):
    nom                  = models.CharField(max_length=100, verbose_name='Nom')
    prenom               = models.CharField(max_length=100, blank=True, verbose_name='Prénom')
    email                = models.EmailField(blank=True, verbose_name='Email')
    telephone            = models.CharField(max_length=20, blank=True, verbose_name='Téléphone')
    societe              = models.CharField(max_length=200, blank=True, verbose_name='Société')
    statut               = models.CharField(
        max_length=20, choices=ProspectStatut.choices, default=ProspectStatut.NOUVEAU,
        verbose_name='Statut'
    )
    source               = models.CharField(
        max_length=20, choices=ProspectSource.choices, default=ProspectSource.AUTRE,
        verbose_name='Source'
    )
    notes                = models.TextField(blank=True, verbose_name='Notes')
    date_dernier_contact = models.DateField(null=True, blank=True, verbose_name='Dernier contact')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='prospects_crees',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Prospect'
        verbose_name_plural = 'Prospects'

    def __str__(self):
        if self.societe:
            return f"{self.societe} — {self.nom} {self.prenom}".strip()
        return f"{self.nom} {self.prenom}".strip()


# ── FACTURE ──────────────────────────────────────────────────────────────────

class FactureStatut(models.TextChoices):
    BROUILLON = 'BROUILLON', 'Brouillon'
    ENVOYEE   = 'ENVOYEE',   'Envoyée'
    PAYEE     = 'PAYEE',     'Payée'
    EN_RETARD = 'EN_RETARD', 'En retard'
    ANNULEE   = 'ANNULEE',   'Annulée'


class FactureType(models.TextChoices):
    PONCTUELLE = 'PONCTUELLE', 'Facture ponctuelle'
    RECURRENTE = 'RECURRENTE', 'Facture récurrente (modèle)'


class RecurrenceFrequence(models.TextChoices):
    MENSUELLE     = 'MENSUELLE',     'Mensuelle'
    TRIMESTRIELLE = 'TRIMESTRIELLE', 'Trimestrielle'
    ANNUELLE      = 'ANNUELLE',      'Annuelle'


class Facture(models.Model):
    numero         = models.CharField(max_length=20, unique=True, blank=True, verbose_name='Numéro')
    client         = models.ForeignKey(
        Client, on_delete=models.PROTECT, related_name='factures', verbose_name='Client'
    )
    objet          = models.CharField(max_length=300, verbose_name='Objet')
    montant_ht     = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name='Montant HT')
    subtotal_ht    = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name='Sous-total HT')
    tva_rate       = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('20.00'), verbose_name='Taux TVA (%)')
    tva_amount     = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name='Montant TVA')
    total_ttc      = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name='Total TTC')
    statut         = models.CharField(
        max_length=20, choices=FactureStatut.choices, default=FactureStatut.BROUILLON,
        verbose_name='Statut'
    )
    date_emission  = models.DateField(default=timezone.now, verbose_name="Date d'émission")
    date_echeance  = models.DateField(null=True, blank=True, verbose_name="Date d'échéance")
    notes          = models.TextField(blank=True, verbose_name='Notes')

    # Récurrence
    type_facture = models.CharField(
        max_length=20, choices=FactureType.choices, default=FactureType.PONCTUELLE,
        verbose_name='Type de facture'
    )
    recurrence_frequence = models.CharField(
        max_length=20, choices=RecurrenceFrequence.choices,
        null=True, blank=True, verbose_name='Fréquence de récurrence'
    )
    recurrence_debut     = models.DateField(null=True, blank=True, verbose_name='Date de début de récurrence')
    recurrence_fin       = models.DateField(null=True, blank=True, verbose_name='Date de fin de récurrence')
    recurrence_prochaine = models.DateField(null=True, blank=True, verbose_name='Prochaine génération')
    recurrence_active    = models.BooleanField(default=True, verbose_name='Récurrence active')
    source_recurring     = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='factures_generees', verbose_name='Facture source récurrente'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='factures_creees',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_emission', '-created_at']
        verbose_name = 'Facture'
        verbose_name_plural = 'Factures'

    def clean(self):
        errors = {}
        is_recurring = self.type_facture == FactureType.RECURRENTE

        if is_recurring:
            if not self.recurrence_frequence:
                errors['recurrence_frequence'] = "La fréquence est requise pour une facture récurrente."
            if not self.recurrence_debut:
                errors['recurrence_debut'] = "La date de début est requise pour une facture récurrente."
            if self.recurrence_fin and self.recurrence_debut and self.recurrence_fin < self.recurrence_debut:
                errors['recurrence_fin'] = "La date de fin doit être postérieure ou égale à la date de début."
            if self.source_recurring:
                errors['source_recurring'] = "Un modèle récurrent ne peut pas référencer une facture source."
        else:
            # Facture ponctuelle : les champs de récurrence doivent rester vides
            if self.recurrence_frequence or self.recurrence_debut or self.recurrence_fin:
                errors['type_facture'] = "Les champs de récurrence ne sont autorisés que pour une facture récurrente."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.numero:
            year = timezone.now().year
            last = Facture.objects.filter(
                numero__startswith=f"FAC-{year}-"
            ).order_by('numero').last()
            base_seq = 288 if year == 2026 else 1
            if last:
                try:
                    seq = int(last.numero.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    seq = base_seq
            else:
                # Démarre à FAC-2026-0288 uniquement pour 2026, sinon FAC-YYYY-0001
                seq = base_seq
            # Garantit qu'on ne repasse jamais sous la séquence de départ de l'année
            if seq < base_seq:
                seq = base_seq
            self.numero = f"FAC-{year}-{seq:04d}"

        # Initialiser la prochaine génération pour les modèles récurrents
        if self.type_facture == FactureType.RECURRENTE:
            if self.recurrence_debut and self.recurrence_frequence:
                # (Re)calcule systématiquement la prochaine génération à partir du début + fréquence
                from .services import calculate_next_generation_date
                self.recurrence_prochaine = calculate_next_generation_date(
                    self.recurrence_debut, self.recurrence_frequence
                )
        else:
            # Facture ponctuelle : pas de récurrence propre
            self.recurrence_active = False
            self.recurrence_frequence = None
            self.recurrence_debut = None
            self.recurrence_fin = None
            self.recurrence_prochaine = None

        super().save(*args, **kwargs)

    def _quantize(self, value: Decimal) -> Decimal:
        return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def recompute_totals(self, save: bool = False):
        lines = list(self.lignes.all())
        subtotal = sum((l.total_ht for l in lines), Decimal('0.00'))
        tva = self._quantize(subtotal * (self.tva_rate / Decimal('100')))
        total = self._quantize(subtotal + tva)
        self.subtotal_ht = self._quantize(subtotal)
        self.montant_ht = self.subtotal_ht  # backward compat
        self.tva_amount = tva
        self.total_ttc = total
        if save:
            super().save(update_fields=['subtotal_ht', 'montant_ht', 'tva_amount', 'total_ttc', 'updated_at'])
        return self.subtotal_ht, self.tva_amount, self.total_ttc

    # ——— Récurrence utilitaires ———
    def is_recurring_template(self) -> bool:
        return self.type_facture == FactureType.RECURRENTE

    def recurrence_interval_months(self) -> int:
        if self.recurrence_frequence == RecurrenceFrequence.MENSUELLE:
            return 1
        if self.recurrence_frequence == RecurrenceFrequence.TRIMESTRIELLE:
            return 3
        if self.recurrence_frequence == RecurrenceFrequence.ANNUELLE:
            return 12
        return 0

    def next_recurrence_date(self) -> date | None:
        return self.recurrence_prochaine

    def recurrence_offset_days(self) -> int:
        if self.date_emission and self.date_echeance:
            return (self.date_echeance - self.date_emission).days
        return 0

    def __str__(self):
        return f"{self.numero} — {self.client}"


class LigneFacture(models.Model):
    facture       = models.ForeignKey(
        Facture, on_delete=models.CASCADE, related_name='lignes'
    )
    description   = models.CharField(max_length=300, verbose_name='Description')
    quantite      = models.DecimalField(
        max_digits=10, decimal_places=2, default=1, verbose_name='Quantité'
    )
    prix_unitaire = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name='Prix unitaire HT')
    item_type     = models.CharField(
        max_length=20,
        choices=(('NORMAL', 'Ligne'), ('DEBOURS', 'Débours')),
        default='NORMAL',
        verbose_name='Type de ligne'
    )

    class Meta:
        verbose_name = 'Ligne de facture'
        verbose_name_plural = 'Lignes de facture'

    @property
    def total_ht(self):
        return (self.quantite * self.prix_unitaire).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def __str__(self):
        return f"{self.description} ×{self.quantite}"


class FactureEmailLog(models.Model):
    facture       = models.ForeignKey(Facture, on_delete=models.CASCADE, related_name='email_logs')
    to_email      = models.CharField(max_length=255)
    cc_email      = models.CharField(max_length=255, blank=True)
    subject       = models.CharField(max_length=255)
    success       = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    sent_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']
        verbose_name = 'Historique envoi facture'
        verbose_name_plural = 'Historique envoi factures'

    def __str__(self):
        status = "OK" if self.success else "KO"
        return f"{self.facture.numero} → {self.to_email} ({status})"

