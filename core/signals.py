from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, Wallet


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile_and_wallet(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
        Wallet.objects.create(user=instance)
