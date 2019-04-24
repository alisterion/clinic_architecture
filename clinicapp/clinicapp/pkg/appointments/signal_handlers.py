from django.db.models import F
from django.db.models.signals import post_save, pre_save, pre_delete
from django.dispatch import receiver

from clinicapp.pkg.appointments.models import AppointmentRating


@receiver(pre_save, sender=AppointmentRating)
def decrease_clinic_rating(instance, **kwargs):
    if instance.pk is None:
        return

    try:
        clinic = instance.appointment.clinic
    except AttributeError:
        return
    if clinic is None:
        return
    rating = AppointmentRating.objects.get(pk=instance.pk)

    clinic.sum_rating = F('sum_rating') - rating.rate
    clinic.cnt_rating = F('cnt_rating') - 1
    clinic.save(update_fields=['sum_rating', 'cnt_rating', ])


@receiver(post_save, sender=AppointmentRating)
def increase_clinic_rating(instance, **kwargs):
    try:
        clinic = instance.appointment.clinic
    except AttributeError:
        return
    if clinic is None:
        return

    clinic.sum_rating = F('sum_rating') + instance.rate
    clinic.cnt_rating = F('cnt_rating') + 1
    clinic.save(update_fields=['sum_rating', 'cnt_rating', ])


@receiver(pre_delete, sender=AppointmentRating)
def delete_clinic_rating(instance, **kwargs):
    try:
        clinic = instance.appointment.clinic
    except AttributeError:
        return
    if clinic is None:
        return

    clinic.sum_rating = F('sum_rating') - instance.rate
    clinic.cnt_rating = F('cnt_rating') - 1
    clinic.save(update_fields=['sum_rating', 'cnt_rating', ])
