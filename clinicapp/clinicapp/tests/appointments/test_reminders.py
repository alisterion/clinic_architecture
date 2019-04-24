import json
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils.timezone import now as tz_now, now
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase

from clinicapp.pkg.appointments.choices import AppointmentState, \
    AppointmentClinicState
from clinicapp.pkg.appointments.models import ReminderTime, AppointmentReminder
from clinicapp.pkg.appointments.tasks import _check_reminders
from clinicapp.pkg.notifications.messages import AppointmentReminderPushMessage
from clinicapp.pkg.users.services.user_service import GroupService
from clinicapp.tests.utils import UserRecipe, AppointmentRecipe, \
    AppointmentReminderRecipe, TreatmentRecipe, AppointmentEventRecipe, \
    ReminderTimeRecipe


@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True,
                   CELERY_ALWAYS_EAGER=True,
                   BROKER_BACKEND='memory')
class TestReminderApi(APITestCase):

    api_appointment_reminder_pattern = 'appointment-reminders'
    api_reminder_pattern = 'reminder'

    def setUp(self):
        self.user = UserRecipe.make(email='user@test.com')
        self.admin = UserRecipe.make(email='admin@test.com')
        self.admin.groups.add(GroupService.get_super_admin())
        self.client.force_login(self.user)
        self.appointment = AppointmentRecipe.make(
            patient=self.user, status=AppointmentState.Confirmed.value,
            date_time=tz_now() + timedelta(days=4)
        )
        self.appointment1 = AppointmentRecipe.make(
            patient=self.user, status=AppointmentState.Confirmed.value,
            date_time=tz_now() + timedelta(days=4)
        )
        reminder_time = ReminderTimeRecipe.make(
            duration=10, time_type='minutes')
        self.default_reminders = ReminderTimeRecipe.make(
            _quantity=2, is_default=True, duration=30, time_type='minutes')
        self.reminder = AppointmentReminderRecipe.make(
            reminder_time=reminder_time, appointment=self.appointment1)
        self.treatment = TreatmentRecipe.make()

    def _get_data(self, **kwargs):
        data = {
            'duration': 10,
            'time_type': 'minutes'
        }
        data.update(**kwargs)
        return json.dumps(data)

    def _create_reminder(self, data=None, appointment=None, **kwargs):
        data = data or self._get_data(**kwargs)
        appointment = appointment or self.appointment
        r = self.client.post(
            reverse(self.api_appointment_reminder_pattern,
                    [appointment.pk]),
            data, content_type='application/json')
        return r.status_code, r.json()

    def test_admin_create_reminder_time_response_201(self):
        self.client.force_login(self.admin)
        data = {'duration': 10, 'time_type': 'hours'}
        r = self.client.post(
            reverse(self.api_reminder_pattern + '-list'), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 201, response_data)
        self.assertEquals(response_data['duration'], 10, response_data)

    def test_admin_create_reminder_time_with_big_value_response_400(self):
        self.client.force_login(self.admin)
        data = {'duration': 10000000000000000, 'time_type': 'hours'}
        r = self.client.post(
            reverse(self.api_reminder_pattern + '-list'), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 400, response_data)
        self.assertIn('duration', response_data)

    def test_user_cant_create_reminder_time_response_403(self):
        data = {'duration': 10, 'time_type': 'hours'}
        r = self.client.post(
            reverse(self.api_reminder_pattern + '-list'), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 403, response_data)
        self.assertTrue(response_data)

    def test_admin_update_reminder_response_200(self):
        self.client.force_login(self.admin)
        data = {'duration': 10, 'time_type': 'hours'}
        r = self.client.put(
            reverse(self.api_reminder_pattern + '-detail',
                    [self.default_reminders[0].id]), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(response_data['duration'], 10, response_data)

    def test_admin_delete_reminder_response_204(self):
        self.client.force_login(self.admin)
        r = self.client.delete(
            reverse(self.api_reminder_pattern + '-detail',
                    [self.default_reminders[0].id]))
        self.assertEquals(r.status_code, 204)

    def test_get_reminder_response_200(self):
        r = self.client.get(
            reverse(self.api_appointment_reminder_pattern,
                    [self.appointment1.pk]))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(len(response_data), 3)
        self.assertEquals(response_data[0]['duration'], 10)
        self.assertEquals(response_data[0]['time_type'], 'minutes')

    def test_after_added_reminders_their_not_duplicate(self):
        data = json.dumps({'reminder_time_id': self.default_reminders[0].id})
        self._create_reminder(data, appointment=self.appointment)
        self._create_reminder(data, appointment=self.appointment1)

        r = self.client.get(
            reverse(self.api_appointment_reminder_pattern,
                    [self.appointment1.pk]))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(len(response_data), len(self.default_reminders))

    def test_get_reminder_with_bad_pk_response_404(self):
        r = self.client.get(
            reverse(self.api_appointment_reminder_pattern, ['868545645']))
        response_data = r.json()
        self.assertEquals(r.status_code, 404, response_data)
        self.assertTrue(response_data)

    def test_create_reminder_for_appointment_response_200(self):
        code, response_data = self._create_reminder(
            appointment=self.appointment1)
        self.assertEquals(code, 200, response_data)
        self.assertTrue(response_data)

    def test_create_default_reminder_for_appointment_response_200(self):
        data = json.dumps({'reminder_time_id': self.default_reminders[0].id})
        code, response_data = self._create_reminder(data)
        self.assertEquals(code, 200, response_data)
        self.assertTrue(response_data)

    def test_create_reminder_with_bad_data_response_400(self):
        code, response_data = self._create_reminder(duration=15000000000000000)
        self.assertEquals(code, 400, response_data)
        self.assertIn('duration', response_data)

    def test_create_reminder_without_valid_data_response_400(self):
        code, response_data = self._create_reminder({'data': 1})
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_create_reminder_with_two_reminder_options_response_400(self):
        code, response_data = self._create_reminder(
            reminder_time_id=self.default_reminders[0].id)
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_create_reminder_with_negative_duration_response_400(self):
        code, response_data = self._create_reminder(duration=-10)
        self.assertEquals(code, 400, response_data)
        self.assertIn('duration', response_data)

    def test_update_reminder_response_200(self):
        data = json.dumps({'duration': 20, "time_type": "hours"})
        code, response_data = self._create_reminder(
            data, appointment=self.appointment1)
        self.assertEquals(code, 200, response_data)
        self.assertEquals(response_data['reminder_time']['duration'], 20)

    def test_update_default_reminder_response_200(self):
        data = json.dumps({'reminder_time_id': self.default_reminders[0].id})
        self._create_reminder(data)
        data = json.dumps({'duration': 20, "time_type": "hours"})
        code, response_data = self._create_reminder(data)
        self.assertEquals(code, 200, response_data)
        self.assertIn('appointment', response_data)

    def test_cant_add_reminder_in_the_past_response_400(self):
        self.appointment.date_time = tz_now() + timedelta(hours=1)
        self.appointment.save()
        code, response_data = self._create_reminder(
            duration=2, time_type='hours')
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_user_add_new_default_reminder_the_old_custom_will_deleted(self):
        self._create_reminder(appointment=self.appointment1)

        cnt_before = ReminderTime.objects.count()

        data = json.dumps({
            "reminder_time_id": self.default_reminders[0].id,
            "appointment": self.appointment1.pk
        })
        self._create_reminder(data, appointment=self.appointment1)
        cnt_after = ReminderTime.objects.count()

        self.assertEquals(cnt_before, cnt_after + 1)

    def test_cant_add_reminder_when_appointment_not_booked(self):
        self.appointment.status = AppointmentState.Reserved.value
        self.appointment.save()
        code, response_data = self._create_reminder()
        self.assertEquals(code, 404, response_data)
        self.assertTrue(response_data)

    def test_delete_reminder_response_204(self):
        r = self.client.delete(
            reverse(self.api_appointment_reminder_pattern,
                    [self.appointment1.pk]))
        self.assertEquals(r.status_code, 204)
        self.assertFalse(r.content)

    def test_check_reminders_run_async_task_for_send_notification(self, *args):
        app = AppointmentRecipe.make(
            date_time=tz_now() + timedelta(minutes=30), patient=self.user,
            status=AppointmentState.Confirmed.value
        )
        AppointmentEventRecipe.make(
            appointment=app, status=AppointmentClinicState.Accepted.value
        )
        with mock.patch('clinicapp.pkg.appointments.serializers.'
                        'run_task_for_reminder_in_saving'):
            self._create_reminder(appointment=app)

        _check_reminders()

        self.assertTrue(app.reminder.already_send)


class TestReminderNotification(APITestCase):

    api_reminder_pattern = 'appointment-reminders'

    def setUp(self):
        self.user = UserRecipe.make(email='user@test.com')
        self.client.force_login(self.user)
        self.appointment = AppointmentRecipe.make(
            patient=self.user, status=AppointmentState.Confirmed.value,
            date_time=now() + timedelta(minutes=30)
        )
        self.event = AppointmentEventRecipe.make(
            appointment=self.appointment,
            status=AppointmentClinicState.Accepted.value
        )

    def _get_data(self, **kwargs):
        data = {
            'appointment': self.appointment.pk,
            'duration': 10,
            'time_type': 'minutes'
        }
        data.update(**kwargs)
        return data

    @override_settings(CELERY_ALWAYS_EAGER=True)
    def test_reminders_run_async_task_for_send_push_notification(self, *args):
        data = self._get_data()
        with mock.patch('clinicapp.pkg.notifications.messenger.Messenger.'
                        'send_push_notifications') as push_call:
            self.client.post(
                reverse(self.api_reminder_pattern, [self.appointment.pk]),
                data
            )

            self.assertTrue(self.appointment.reminder.already_send)
            self.assertEquals(push_call.call_count, 1)
            self.assertEquals(push_call.call_args[0][0], self.user)
            self.assertTrue(isinstance(push_call.call_args[0][1],
                                       AppointmentReminderPushMessage))

    @override_settings(CELERY_ALWAYS_EAGER=True)
    def test_reminder_already_sent_reminder_time_is_none(self):
        data = self._get_data()
        with mock.patch('clinicapp.pkg.notifications.messenger.Messenger.'
                        'send_push_notifications') as push_call:
            self.client.post(
                reverse(self.api_reminder_pattern, [self.appointment.pk]),
                data
            )
        self.assertIsNone(self.appointment.reminder.reminder_time)
