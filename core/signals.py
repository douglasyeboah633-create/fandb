"""Signal handlers that keep land status consistent with sales."""

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Land, Sale


@receiver(pre_save, sender=Sale)
def remember_previous_land(sender, instance, raw=False, **kwargs):
    if raw:
        return
    instance._previous_land_id = (
        Sale.objects.filter(pk=instance.pk).values_list("land_id", flat=True).first()
        if instance.pk else None
    )


@receiver(post_save, sender=Sale)
def mark_land_as_sold(sender, instance, raw=False, **kwargs):
    """Keep both plots consistent when a sale is created or reassigned."""
    if raw:
        return
    old_id = getattr(instance, "_previous_land_id", None)
    if old_id and old_id != instance.land_id:
        Land.objects.filter(pk=old_id, sale__isnull=True, status=Land.STATUS_SOLD).update(
            status=Land.STATUS_AVAILABLE
        )
    Land.objects.filter(pk=instance.land_id).exclude(
        status=Land.STATUS_SOLD
    ).update(status=Land.STATUS_SOLD)


@receiver(post_delete, sender=Sale)
def release_land_on_sale_deletion(sender, instance, **kwargs):
    """Deleting a sale releases the land back to Available."""
    Land.objects.filter(pk=instance.land_id, status=Land.STATUS_SOLD).update(
        status=Land.STATUS_AVAILABLE
    )
