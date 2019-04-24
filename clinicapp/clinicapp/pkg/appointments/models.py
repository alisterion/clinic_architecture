from datetime import timedelta

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.fields import DateTimeRangeField
from django.db.models import Q
from django.db.transaction import atomic
from django_extensions.db.models import TimeStampedModel
from psycopg2.extras import DateTimeTZRange

from clinicapp.pkg.appointments.choices import (
    AppointmentClinicState, AppointmentState, ReminderTimeType
)
from clinicapp.pkg.clinics.models import Treatment, Clinic
from clinicapp.pkg.notifications.messages import AppointmentReminderPushMessage


class Appointment(TimeStampedModel):
    """
    Model represent user request for create appointment.
    User can choose location and must add treatments to basket,
    must choose date and time.
    """
    class Meta:
        db_table = 'appointments'

    patient = models.ForeignKey(settings.AUTH_USER_MODEL,
                                related_name='self_appointments')
    location = models.PointField(srid=4326, null=True, blank=True)
    basket = models.OneToOneField('users.Basket', null=True)
    date_time = models.DateTimeField()
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        related_name='appointments')
    clinic = models.ForeignKey(Clinic, related_name='appointments',
                               null=True, blank=True)
    adjust_30_min = models.BooleanField(default=False, blank=True)
    status = models.PositiveIntegerField(
        choices=AppointmentState.choices(),
        default=AppointmentState.Opened.value
    )

    def __str__(self):
        return "Appointment {} for {}".format(self.id, self.patient)

    def set_canceled(self):
        if self.status <= AppointmentState.Confirmed.value:
            self.status = AppointmentState.Canceled.value
            self.save(update_fields=['status', ])
        else:
            raise ValueError(
                "You can not cancel appointment with status %s"
                % self.status_description
            )

    def set_opened(self):
        if self.status in [
            AppointmentState.TimeOut.value,
            AppointmentState.UserRejectSuggestions.value,
        ]:
            self.status = AppointmentState.Opened.value
            self.save(update_fields=['status', ])
        else:
            raise ValueError(
                "You can not reopen appointment with status %s"
                % self.status_description
            )

    def set_reserved(self, clinic: Clinic, force_save=True):
        if self.status in [
            AppointmentState.Opened.value,
            AppointmentState.WaitingForUserDecide.value
        ]:
            self.status = AppointmentState.Reserved.value
            self.clinic = clinic
            if force_save:
                self.save(update_fields=['status', 'clinic', ])
        else:
            raise ValueError(
                "You can not reserve appointment with status %s"
                % self.status_description
            )

    def set_confirmed(self):
        if self.status == AppointmentState.Reserved.value:
            self.status = AppointmentState.Confirmed.value
            self.save(update_fields=['status'])
        else:
            raise ValueError(
                "You can not book appointment with status {}".format(
                    self.status_description
                )
            )

    def set_wait_for_user(self):
        if self.status == AppointmentState.Opened.value:
            self.status = AppointmentState.WaitingForUserDecide.value
            self.save(update_fields=['status', ])
        else:
            raise ValueError(
                "You can not add suggestions to appointment in status %s"
                % self.status_description
            )

    def set_reject_suggestions(self):
        if self.status == AppointmentState.WaitingForUserDecide.value:
            self.status = AppointmentState.UserRejectSuggestions.value
            self.save(update_fields=['status', ])
        else:
            raise ValueError(
                "You can not reject suggestions to appointment in status %s"
                % self.status_description
            )

    def set_timeout(self):
        if self.status in [AppointmentState.Opened.value,
                           AppointmentState.WaitingForUserDecide.value]:
            self.status = AppointmentState.TimeOut.value
            self.save(update_fields=['status', ])
        else:
            raise ValueError(
                "You can not set timeout to appointment in status %s"
                % self.status_description
            )

    @property
    def treatments(self):
        try:
            return self.basket.treatments
        except AttributeError:
            return Treatment.objects.none()

    @property
    def is_opened(self):
        return self.status == AppointmentState.Opened.value

    @property
    def is_reserved(self):
        return self.status == AppointmentState.Reserved.value

    @property
    def is_waiting_for_user(self):
        return self.status == AppointmentState.WaitingForUserDecide.value

    @property
    def status_description(self):
        return dict(AppointmentState.choices()).get(self.status)

    def get_clinic(self):
        if self.clinic:
            return self.clinic
        if self.status not in [
            AppointmentState.Reserved.value, AppointmentState.Confirmed.value
        ]:
            return None
        events = self.events.filter(
            Q(status=AppointmentClinicState.Accepted.value) |
            Q(status=AppointmentClinicState.Suggested.value)
        )
        try:
            clinic = events.get().clinic
        except (AppointmentClinicEvent.MultipleObjectsReturned,
                AppointmentClinicEvent.DoesNotExist):
            clinic = None
        return clinic


class AppointmentClinicEvent(models.Model):
    """
    Model represent clinic's admin decide for appointment
    (accept, reject, suggested or inactive if other admin accept request).
    Instance created for each clinic, which receive a notification
    about new request for appointment, and there are two types
    of clinic's admin actions:
        1. Clinic's admin select doctor for appointment and may
           include adjust_30_min parameter.
           In this way clinic receive appointment, status will be Accepted
           and for other clinic status will be Inactive
        2. Clinic's admin just reject appointment, and status will be Rejected
    """
    class Meta:
        db_table = 'appointment_actions'

    appointment = models.ForeignKey(Appointment, related_name='events')
    clinic = models.ForeignKey(Clinic, related_name='appointment_events')
    status = models.PositiveIntegerField(
        choices=AppointmentClinicState.choices(),
        default=AppointmentClinicState.Active.value
    )

    def __str__(self):
        return "Action for appointment {} by clinic {}".format(
            self.appointment_id, self.clinic)

    @property
    def is_opened(self):
        return self.status == AppointmentClinicState.Active.value

    @property
    def is_suggested(self):
        return self.status == AppointmentClinicState.Suggested.value

    @property
    def status_description(self):
        return dict(AppointmentClinicState.choices()).get(self.status)

    def _set_status(self, state, current_status=AppointmentClinicState.Active,
                    raise_exception=True):
        if self.status == current_status:
            self.status = state.value
            self.save(update_fields=['status', ])
            return
        if raise_exception:
            raise ValueError(
                "You can not do %s in appointment with status %s"
                % (state.name, self.status_description)
            )

    def set_active(self):
        self.status = AppointmentClinicState.Active.value
        self.save(update_fields=['status'])

    def set_reject(self):
        self._set_status(AppointmentClinicState.Rejected)

    def set_accept(self):
        self._set_status(AppointmentClinicState.Accepted)

    def set_suggested(self):
        self._set_status(AppointmentClinicState.Suggested)

    def set_inactive(self):
        self._set_status(AppointmentClinicState.Inactive,
                         raise_exception=False)

    def set_rejected_suggestions(self):
        self._set_status(AppointmentClinicState.RejectedSuggestions,
                         AppointmentClinicState.Suggested)


class AppointmentSuggestion(models.Model):
    """
    Model represent clinic's admin suggestions when admin
    accept appointment and want to change date and/or time.
    """
    class Meta:
        db_table = 'appointment_suggestions'

    appointment_event = models.ForeignKey(
        AppointmentClinicEvent, related_name='suggestions')
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL,
                               related_name='in_suggestions')
    adjust_30_min = models.BooleanField(default=False, blank=True)
    date_time = models.DateTimeField()
    is_chosen = models.NullBooleanField(null=True, blank=True)

    def __str__(self):
        return "Suggestion for appointment {} by clinic {}".format(
            self.appointment_event.appointment_id,
            self.appointment_event.clinic
        )

    @atomic()
    def chose(self):
        self.is_chosen = True
        self.save(update_fields=['is_chosen', ])
        self.appointment_event.appointment.doctor = self.doctor
        self.appointment_event.appointment.adjust_30_min = self.adjust_30_min
        self.appointment_event.appointment.date_time = self.date_time
        self.appointment_event.appointment.set_reserved(
            self.appointment_event.clinic, force_save=False)
        self.appointment_event.appointment.save()


class AppointmentSchedule(models.Model):
    """
    Model represent schedule for booked appointment.
    The end of appointment will automatic calculated from treatments duration
    """
    class Meta:
        db_table = 'appointment_schedules'

    appointment = models.OneToOneField(Appointment, related_name='schedule')
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL,
                               related_name='appointment_schedules')
    duration = DateTimeRangeField(null=True)

    def __str__(self):
        return "Appointment {} for doctor {} at {}".format(
            self.appointment_id, self.doctor, self.duration
        )

    @staticmethod
    def create_from(appointment: Appointment):
        appointment = Appointment.objects.get(pk=appointment.pk)
        treatments_duration = sum([
            getattr(t, 'duration', 0) for t in appointment.treatments.all()
        ])
        start_time = appointment.date_time
        end_time = start_time + timedelta(minutes=treatments_duration)
        try:
            appointment_schedule = AppointmentSchedule.objects.get(
                appointment=appointment)
        except AppointmentSchedule.DoesNotExist:
            appointment_schedule = AppointmentSchedule(appointment=appointment)

        appointment_schedule.doctor = appointment.doctor
        appointment_schedule.duration = DateTimeTZRange(start_time, end_time)
        appointment_schedule.save()
        return appointment_schedule


class ReminderTime(models.Model):
    """
    Set of time types for reminder.
    Super admin can change list of defaults time types.
    """
    class Meta:
        db_table = 'reminder_time_types'

    before = models.DurationField(blank=True)
    duration = models.PositiveIntegerField()
    time_type = models.CharField(
        max_length=10, choices=ReminderTimeType.choices(),
        default=ReminderTimeType.Minutes.value
    )
    is_default = models.BooleanField(default=False)

    def save(self, **kwargs):
        self.before = timedelta(**{self.time_type: self.duration})
        super(ReminderTime, self).save(**kwargs)

    def __str__(self):
        return "{} {}".format(self.duration, self.time_type)


class AppointmentReminder(models.Model):
    """
    Reminder for user before appointment.
    """
    class Meta:
        db_table = 'appointment_reminders'

    appointment = models.OneToOneField(Appointment, related_name='reminder')
    reminder_time = models.ForeignKey(ReminderTime,  null=True,
                                      related_name='appointment_reminder')
    already_send = models.BooleanField(default=False)
    task_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return "Reminder before {} for appointment {}".format(
            getattr(self.reminder_time, 'before', None),
            self.appointment_id
        )

    def send(self):
        from clinicapp.pkg.notifications.messenger import Messenger
        msg = AppointmentReminderPushMessage(
            self.appointment.date_time, self.appointment.get_clinic()
        )
        Messenger(
            self.appointment.patient,
            push_message=msg,
            show_in_list=True,
            push_message_extra_data={'appointment_id': self.appointment.id}
        ).send()
        self.already_send = True
        self.reminder_time = None
        self.save(update_fields=['already_send', 'reminder_time'])


class AppointmentRating(TimeStampedModel):
    """
    User's rating for appointment (btw for clinic as well)
    """
    class Meta:
        db_table = 'appointment_ratings'

    appointment = models.OneToOneField(Appointment, related_name='rating')
    rate = models.PositiveSmallIntegerField()
    comment = models.CharField(max_length=1023)

    def __str__(self):
        return "Appointment {}: {}...".format(
            self.appointment_id, self.comment[:10]
        )
