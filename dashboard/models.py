from django.db import models
from django.conf import settings
from django.utils import timezone


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


class Facture(models.Model):
    numero         = models.CharField(max_length=20, unique=True, blank=True, verbose_name='Numéro')
    client         = models.ForeignKey(
        Client, on_delete=models.PROTECT, related_name='factures', verbose_name='Client'
    )
    objet          = models.CharField(max_length=300, verbose_name='Objet')
    montant_ht     = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name='Montant HT'
    )
    taux_tva       = models.DecimalField(
        max_digits=5, decimal_places=2, default=20, verbose_name='Taux TVA (%)'
    )
    statut         = models.CharField(
        max_length=20, choices=FactureStatut.choices, default=FactureStatut.BROUILLON,
        verbose_name='Statut'
    )
    date_emission  = models.DateField(default=timezone.now, verbose_name="Date d'émission")
    date_echeance  = models.DateField(null=True, blank=True, verbose_name="Date d'échéance")
    notes          = models.TextField(blank=True, verbose_name='Notes')
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

    def save(self, *args, **kwargs):
        if not self.numero:
            year = timezone.now().year
            last = Facture.objects.filter(
                numero__startswith=f"FAC-{year}-"
            ).order_by('numero').last()
            if last:
                try:
                    seq = int(last.numero.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            self.numero = f"FAC-{year}-{seq:04d}"
        super().save(*args, **kwargs)

    @property
    def montant_ttc(self):
        return round(float(self.montant_ht) * (1 + float(self.taux_tva) / 100), 2)

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
    prix_unitaire = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name='Prix unitaire HT'
    )

    class Meta:
        verbose_name = 'Ligne de facture'
        verbose_name_plural = 'Lignes de facture'

    @property
    def montant(self):
        return round(float(self.quantite) * float(self.prix_unitaire), 2)

    def __str__(self):
        return f"{self.description} ×{self.quantite}"

