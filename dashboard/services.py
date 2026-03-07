from decimal import Decimal, ROUND_HALF_UP


def quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def compute_invoice_totals(facture):
    """
    Recalcule les totaux d'une facture à partir de ses lignes.
    Met à jour subtotal_ht, tva_amount et total_ttc en mémoire.
    """
    subtotal = sum((l.total_ht for l in facture.lignes.all()), Decimal('0.00'))
    tva = quantize(subtotal * (facture.tva_rate / Decimal('100')))
    total = quantize(subtotal + tva)
    facture.subtotal_ht = quantize(subtotal)
    facture.montant_ht = facture.subtotal_ht
    facture.tva_amount = tva
    facture.total_ttc = total
    return facture
