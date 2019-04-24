import logging
from datetime import timedelta, time

from django.conf import settings
from django.utils.timezone import now as tz_now


logger = logging.getLogger(__name__)


def run_task_for_reminder_in_saving(appointment_reminder):
    from clinicapp.pkg.appointments.tasks import send_reminder_to_user
    try:
        execute_at = appointment_reminder.appointment.date_time -\
            appointment_reminder.reminder_time.before
        if execute_at - tz_now() <= timedelta(hours=1):
            task = send_reminder_to_user.apply_async(
                args=[appointment_reminder.id], eta=execute_at,
                expires=appointment_reminder.appointment.date_time
            )
            appointment_reminder.task_id = task.task_id
            appointment_reminder.save(update_fields=['task_id'])
    except (TypeError, ValueError, AttributeError) as e:
        logger.error(e)
        print(e)


class SupportAdminTime(object):
    def __init__(self):
        self.is_support_admin_time = self._support_admin_time()

    def countdown_open(self):
        if self.is_support_admin_time:
            return settings.SUPPORT_ADMIN_CHECK_APPOINTMENT_EXPIRED_AFTER_OPEN
        else:
            return settings.CLINIC_ADMIN_CHECK_APPOINTMENT_EXPIRED_AFTER_OPEN

    def _support_admin_time(self):
        end = time(settings.SUPPORT_ADMIN_END_HOUR)
        start = time(settings.SUPPORT_ADMIN_START_HOUR)
        return end >= tz_now().time() >= start