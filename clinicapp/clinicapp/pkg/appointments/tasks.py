import logging
from datetime import timedelta

from celery.schedules import crontab
from celery.task import periodic_task
from django.db.models import F, ExpressionWrapper, DateTimeField, Sum
from django.utils.timezone import now as tz_now

from clinicapp.celery import app
from clinicapp.pkg.appointments.choices import AppointmentState
from clinicapp.pkg.appointments.models import Appointment, AppointmentReminder
from clinicapp.pkg.appointments.actions import AppointmentActions, \
    AppointmentClinicSearcher
from clinicapp.pkg.appointments.utils import SupportAdminTime
from clinicapp.pkg.notifications.messages import RatingAppointmentPushMessage
from clinicapp.pkg.notifications.messenger import PushNotificationMessenger, \
    Messenger

logger = logging.getLogger(__name__)


@app.task
def check_status_appointment_after_open(appointment_id: int):
    try:
        appointment = Appointment.objects.get(pk=appointment_id)
    except Appointment.DoesNotExist as e:
        print(e)
        logger.error(e)
        return

    if appointment.status != AppointmentState.Opened.value:
        return

    if appointment.location is not None:
        longitude = appointment.location.get_x()
        latitude = appointment.location.get_y()
    else:
        longitude, latitude = None, None

    searcher = AppointmentClinicSearcher(
        appointment.treatments,
        longitude=longitude,
        latitude=latitude,
        appointment=appointment,
        raise_exception=False,
        use_additional_filters=True
    )
    AppointmentActions(
        appointment,
        SupportAdminTime().is_support_admin_time
    ).timeout(searcher.get_suggestions_time())


@app.task
def check_status_appointment_after_suggest(appointment_id: int):
    try:
        appointment = Appointment.objects.get(pk=appointment_id)
    except Appointment.DoesNotExist as e:
        print(e)
        logger.error(e)
        return

    if appointment.status == AppointmentState.WaitingForUserDecide.value:
        AppointmentActions(
            appointment,
            SupportAdminTime().is_support_admin_time
        ).cancel(notif_user=True)


@app.task
def check_status_appointment_after_reserved(appointment_id: int):
    try:
        appointment = Appointment.objects.get(pk=appointment_id)
    except Appointment.DoesNotExist as e:
        print(e)
        logger.error(e)
        return

    if appointment.status == AppointmentState.Reserved.value:
        AppointmentActions(
            appointment,
            SupportAdminTime().is_support_admin_time
        ).cancel(notif_user=True)


@app.task
def send_reminder_to_user(reminder_id: int):
    try:
        appointment_reminder = AppointmentReminder.objects.get(pk=reminder_id)
    except AppointmentReminder.DoesNotExist as e:
        print(e)
        logger.error(e)
        return

    appointment_reminder.send()


def _check_reminders():
    reminders = AppointmentReminder.objects.select_related('appointment').\
        annotate(execute_at=ExpressionWrapper(
            F('appointment__date_time') - F('reminder_time__before'),
            output_field=DateTimeField()
        )
    ).filter(
        execute_at__lte=tz_now() + timedelta(hours=1),
        already_send=False
    )
    for reminder in reminders:
        if reminder.task_id:
            app.control.revoke(task_id=reminder.task_id, terminate=True)
        task = send_reminder_to_user.apply_async(
            args=[reminder.id], eta=reminder.execute_at,
            expires=reminder.appointment.date_time
        )
        reminder.task_id = task.task_id
        reminder.save(update_fields=['task_id'])


@periodic_task(ignore_result=True, run_every=crontab(minute="*/60"))
def check_reminders():
    _check_reminders()


@app.task
def send_notification_about_rating_to_passed_appointment(appointment_id):
    try:
        appointment = Appointment.objects.get(pk=appointment_id)
    except AppointmentReminder.DoesNotExist as e:
        print(e)
        logger.error(e)
        return
    if getattr(appointment, 'rating', None) is None:
        Messenger(
            appointment.patient,
            push_message=RatingAppointmentPushMessage(),
            show_in_list=True,
            push_message_extra_data={'appointment_id': appointment.id}
        ).send()


def _check_time_for_passed_appointments_for_sending_notification_about_rating():
    now = tz_now()
    appointments = Appointment.objects.annotate(
        finish_at=ExpressionWrapper(
            F('date_time') +
            Sum('basket__treatments__duration') * timedelta(minutes=1),
            output_field=DateTimeField()
        )
    ).filter(
        status=AppointmentState.Confirmed.value,
        rating__isnull=True,
        finish_at__range=[now, now + timedelta(hours=1)]
    )
    for appointment in appointments:
        send_notification_about_rating_to_passed_appointment.apply_async(
            args=[appointment.id],
            eta=appointment.finish_at + timedelta(hours=1),
            expires=appointment.finish_at + timedelta(days=1)
        )


@periodic_task(ignore_result=True, run_every=crontab(minute="*/60"))
def check_time_for_passed_appointments_for_sending_notification_about_rating():
    _check_time_for_passed_appointments_for_sending_notification_about_rating()
