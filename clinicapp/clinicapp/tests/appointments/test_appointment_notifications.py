import time
from datetime import timedelta, datetime

from channels.tests import ChannelTestCase, HttpClient
from django.db.models import F
from django.test import mock, override_settings
from django.utils.timezone import now as tz_now
from rest_framework.authtoken.models import Token
from rest_framework.reverse import reverse

from clinicapp.pkg.appointments.actions import AppointmentActions
from clinicapp.pkg.appointments.tasks import \
    _check_time_for_passed_appointments_for_sending_notification_about_rating
from clinicapp.pkg.clinics.choices import ClinicState
from clinicapp.pkg.notifications.choices import UserNotificationState
from clinicapp.pkg.notifications.messages import RatingAppointmentPushMessage
from clinicapp.pkg.notifications.models import UserNotification
from clinicapp.pkg.users.services.user_service import GroupService
from clinicapp.tests.appointments.base import AppointmentTestMixin
from clinicapp.tests.utils import UserRecipe, ClinicRecipe


@mock.patch('clinicapp.pkg.appointments.views.'
            'check_status_appointment_after_open')
@mock.patch('clinicapp.pkg.appointments.views.'
            'check_status_appointment_after_suggest')
@mock.patch('clinicapp.pkg.appointments.views.'
            'check_status_appointment_after_reserved')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True,
                   CELERY_ALWAYS_EAGER=True,
                   BROKER_BACKEND='memory')
class TestAppointmentNotifications(AppointmentTestMixin, ChannelTestCase):

    def _get_token_for(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        return token

    def test_create_appointment_admins_received_notification(self, *args):
        client1 = HttpClient()
        client1.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        client2 = HttpClient()
        client2.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin2)
        )
        self._create_appointment()
        msg1 = client1.receive()
        msg2 = client2.receive()
        self.assertEquals(msg1.get('action'), 'appointment_created')
        self.assertEquals(msg2.get('action'), 'appointment_created')
        self.assertTrue(msg1.get('message'))

    def test_create_appointment_admin_receive_notification_and_send_confirm(
            self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        self._create_appointment()
        msg = client.receive()
        notification_id = msg.get('notification_id')
        client.send_and_consume("websocket.receive",
                                text={"notification_id": notification_id})
        self.assertEquals(
            UserNotification.objects.get(pk=notification_id).status,
            UserNotificationState.Reviewed.value
        )

    def test_create_appointment_admin_receive_notification_after_connect(
            self, *args):
        self._create_appointment()
        time.sleep(1)
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        msg = client.receive()
        self.assertEquals(msg.get('action'), 'appointment_created')
        self.assertTrue(msg.get('message'))

    def test_create_appointment_notification_expired(self, *args):
        c, r, appointment = self._create_appointment()
        user_notif = UserNotification.objects.get(user=self.clinic_admin1)
        user_notif.expired = F('expired') - timedelta(seconds=58)
        user_notif.save(update_fields=['expired', ])
        time.sleep(2)
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        self.assertIsNone(client.receive())

    def test_cancel_appointment_admins_received_notification(self, *args):
        client1 = HttpClient()
        client1.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        client2 = HttpClient()
        client2.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin2)
        )
        c, r, appointment = self._create_appointment()
        msg1 = client1.receive()
        msg2 = client2.receive()
        self._cancel_appointment(appointment.pk)
        msg1 = client1.receive()
        msg2 = client2.receive()
        self.assertEquals(msg1.get('action'), 'appointment_canceled')
        self.assertEquals(msg2.get('action'), 'appointment_canceled')
        self.assertTrue(msg1.get('message'))

    def test_admin_reject_appointment_and_not_receive_info_more(self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        c, r, appointment = self._create_appointment()
        client.receive()
        event = appointment.events.get(clinic__admin=self.clinic_admin1)
        self.client.force_login(self.clinic_admin1)
        self.client.post(
            reverse(self.api_pattern_event + '-reject', [event.pk]))
        self._cancel_appointment(appointment.pk)
        self.assertIsNone(client.receive())

    def test_admin_accept_appointment_patient_receive_notification(
            self, *args):
        c, r, appointment = self._create_appointment()
        self._accept(appointment, self.clinic_admin1)
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.simple_user)
        )
        msg = client.receive()
        self.assertEquals(msg.get('action'), 'appointment_clinic_accept')
        self.assertTrue(msg.get('message'))

    def test_accept_appointment_others_receive_notification_about_inactive(
            self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin2)
        )
        c, r, appointment = self._create_appointment()
        self._accept(appointment, self.clinic_admin1)
        msg = client.receive()  # first message about creating
        msg = client.receive()
        self.assertEquals(msg.get('action'), 'appointment_inactive')
        self.assertTrue(msg.get('message'))

    def test_admin_suggested_another_time_patient_receive_notification(
            self, *args):
        c, r, appointment = self._create_appointment()
        self._suggest(appointment, self.clinic_admin1)
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.simple_user)
        )
        msg = client.receive()
        self.assertEquals(msg.get('action'), 'appointment_clinic_suggested')
        self.assertTrue(msg.get('message'))

    def test_one_admin_suggested_others_receive_notification_about_inactive(
            self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin2)
        )
        c, r, appointment = self._create_appointment()
        self._suggest(appointment, self.clinic_admin1)
        msg = client.receive()  # first message about creating
        msg = client.receive()
        self.assertEquals(msg.get('action'), 'appointment_inactive')
        self.assertTrue(msg.get('message'))

    def test_user_reject_suggestions_admin_receive_notification(self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        c, r, appointment = self._create_appointment()
        c, r, event = self._suggest(appointment, self.clinic_admin1)
        self._reject_suggestion(event)
        msg = client.receive()  # first message about creating
        msg = client.receive()
        self.assertEquals(msg.get('action'),
                          'appointment_user_reject_suggestions')
        self.assertTrue(msg.get('message'))

    def test_user_accept_suggestion_admin_receive_notification(self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._suggest(appointment, self.clinic_admin1)
        suggestion_id = r.get('suggestions')[0].get('id')
        self._accept_suggestion(event, suggestion_id)
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        msg = client.receive()  # first message about creating
        msg = client.receive()
        self.assertEquals(msg.get('action'),
                          'appointment_user_accept_suggestion')
        self.assertTrue(msg.get('message'))

    def test_after_reopen_clinic_admins_receive_notification(self, *args):
        c, r, appointment = self._create_appointment()
        AppointmentActions(appointment).timeout()

        self._reopen(appointment.pk)

        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        msg = client.receive()
        self.assertEquals(msg.get('action'), 'appointment_created')
        self.assertTrue(msg.get('message', {}).get('appointment_event'))

    def test_clinic_admin_reject_and_not_receive_notification_after_reopen(
            self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        c, r, appointment = self._create_appointment()
        msg = client.receive()  # first message about creating

        self._reject(appointment, self.clinic_admin1)

        AppointmentActions(appointment).timeout()

        self._reopen(appointment.pk)

        msg = client.receive()
        self.assertIsNone(msg)

    def test_reopen_appointment_new_clinic_receive_notification(self, *args):
        client1 = HttpClient()
        client1.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )

        client2 = HttpClient()
        client2.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin2)
        )

        c, r, appointment = self._create_appointment()

        client1.receive()  # first message about creating
        client2.receive()  # first message about creating

        self._reject(appointment, self.clinic_admin1)
        self._reject(appointment, self.clinic_admin2)

        AppointmentActions(appointment).timeout()

        admin = UserRecipe.make(email='clinic3@admin.com', is_active=True)
        admin.groups.add(GroupService.get_clinics_admin())
        clinic = ClinicRecipe.make(admin=admin, location=self.clinic_point1,
                                   status=ClinicState.Approved.value)
        clinic.treatments.add(self.treatment)

        client3 = HttpClient()
        client3.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(admin)
        )

        self._reopen(appointment.pk)

        msg = client3.receive()

        self.assertIsNone(client1.receive())
        self.assertIsNone(client2.receive())
        self.assertEquals(msg.get('action'), 'appointment_created')
        self.assertTrue(msg.get('message', {}).get('appointment_event'))

    def test_appointment_confirmed_push_notification_should_sent_to_user(
            self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.simple_user)
        )
        with mock.patch('clinicapp.pkg.notifications.messenger.Messenger.'
                        'send_push_notifications') as push_call:
            c, r, appointment = self._create_appointment()
            c, r, event = self._accept(appointment, self.clinic_admin1)
            AppointmentActions(event.appointment).confirm(event)
            self.assertEquals(push_call.call_count, 1)
            self.assertEquals(push_call.call_args[0][0], self.simple_user)

    def test_appointment_send_push_notification_about_rating(
            self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.simple_user)
        )
        with mock.patch('clinicapp.pkg.notifications.messenger.Messenger.'
                        'send_push_notifications') as push_call:
            c, r, appointment = self._create_appointment()
            c, r, event = self._accept(appointment, self.clinic_admin1)
            AppointmentActions(event.appointment).confirm(event)

            appointment.refresh_from_db()
            appointment.date_time = tz_now() - timedelta(minutes=30)
            appointment.save()

            _check_time_for_passed_appointments_for_sending_notification_about_rating()

            self.assertEquals(push_call.call_count, 2)
            self.assertEquals(push_call.call_args_list[1][0][0], self.simple_user)
            self.assertIsInstance(push_call.call_args_list[1][0][1],
                                  RatingAppointmentPushMessage)


@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True,
                   CELERY_ALWAYS_EAGER=True,
                   BROKER_BACKEND='memory',
                   SUPPORT_ADMIN_CHECK_APPOINTMENT_EXPIRED_AFTER_OPEN=30)
class TestCheckCeleryTaskAppointmentNotification(
        AppointmentTestMixin, ChannelTestCase):

    def _get_token_for(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        return token

    def test_create_appointment_celery_task_send_notification_to_user(self):
        self._create_appointment()
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.simple_user)
        )
        msg = client.receive()
        self.assertEquals(msg.get('action'),
                          'appointment_timeout_expired')
        self.assertIn('appointment', msg.get('message'))

    def test_create_appointment_celery_task_send_notification_to_admin(self):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        self._create_appointment()
        msg = client.receive()  # first message about creating request
        msg = client.receive()
        self.assertEquals(msg.get('action'),
                          'appointment_timeout_expired')
        self.assertIn('appointment_event', msg.get('message'))

    @mock.patch('clinicapp.pkg.appointments.views.'
                'check_status_appointment_after_open')
    def test_user_not_accept_suggestion_user_receive_appointment_canceled(
            self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.simple_user)
        )
        c, r, appointment = self._create_appointment()
        self._suggest(appointment, self.clinic_admin1)
        msg = client.receive()  # first message about suggestions
        msg = client.receive()
        self.assertEquals(msg.get('action'),
                          'appointment_canceled')
        self.assertIn('appointment', msg.get('message'))

    @mock.patch('clinicapp.pkg.appointments.views.'
                'check_status_appointment_after_open')
    def test_user_not_accept_suggestion_admin_receive_appointment_canceled(
            self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        c, r, appointment = self._create_appointment()
        self._suggest(appointment, self.clinic_admin1)
        msg = client.receive()  # first message about creating
        msg = client.receive()
        self.assertEquals(msg.get('action'),
                          'appointment_canceled')
        self.assertIn('appointment_event', msg.get('message'))

    @mock.patch('clinicapp.pkg.appointments.views.'
                'check_status_appointment_after_open')
    def test_user_not_payment_and_receive_appointment_canceled_after_timeout(
            self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.simple_user)
        )
        c, r, appointment = self._create_appointment()
        self._accept(appointment, self.clinic_admin1)
        msg = client.receive()  # first message about accepting
        msg = client.receive()
        self.assertEquals(msg.get('action'),
                          'appointment_canceled')
        self.assertIn('appointment', msg.get('message'))

    @mock.patch('clinicapp.pkg.appointments.views.'
                'check_status_appointment_after_open')
    def test_user_not_payment_admin_receive_appointment_canceled_after_timeout(
            self, *args):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.clinic_admin1)
        )
        c, r, appointment = self._create_appointment()
        self._accept(appointment, self.clinic_admin1)
        msg = client.receive()  # first message about creating
        msg = client.receive()
        self.assertEquals(msg.get('action'),
                          'appointment_canceled')
        self.assertIn('appointment_event', msg.get('message'))

    @mock.patch(
        'clinicapp.pkg.appointments.utils.SupportAdminTime._support_admin_time',
        lambda _: True
    )
    def test_create_appointment_celery_task_send_notification_to_support_admin(
            self):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.support_admin)
        )
        self._create_appointment()
        msg = client.receive()  # first message about creating request
        msg = client.receive()
        self.assertEquals(msg.get('action'),
                          'appointment_timeout_expired')
        self.assertIn('appointment_event', msg.get('message'))
