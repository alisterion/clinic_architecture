from datetime import timedelta

from django.utils.timezone import now as tz_now
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase

from clinicapp.pkg.appointments.choices import AppointmentState
from clinicapp.tests.utils import UserRecipe, AppointmentRecipe


class TestAppointmentHistory(APITestCase):

    api_pattern_name = 'appointment'

    def setUp(self):
        self._prepare_users()
        self._prepare_appointments()

    def _prepare_users(self):
        self.user = UserRecipe.make(email='test@user.com')
        self.other_user = UserRecipe.make(email='test2@user.com')
        self.client.force_login(self.user)

    def _prepare_appointments(self):
        now = tz_now()
        self.upcoming_appointments = AppointmentRecipe.make(
            date_time=now + timedelta(days=2),
            patient=self.user,
            status=AppointmentState.Confirmed.value,
            _quantity=3
        )
        self.passed_appointments = AppointmentRecipe.make(
            date_time=now - timedelta(days=2),
            patient=self.user,
            status=AppointmentState.Confirmed.value,
            _quantity=2
        )
        AppointmentRecipe.make(patient=self.user, _quantity=2)
        AppointmentRecipe.make(_quantity=2)

    def test_get_list_upcoming_appointments_response_200(self):
        r = self.client.get(reverse(self.api_pattern_name + '-upcoming'))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(len(response_data), 3)

    def test_get_list_passed_appointments_response_200(self):
        r = self.client.get(reverse(self.api_pattern_name + '-passed'))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(len(response_data), 2)

    def test_get_list_upcoming_appointments_for_other_user_empty_response(
            self):
        self.client.force_login(self.other_user)
        r = self.client.get(reverse(self.api_pattern_name + '-upcoming'))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(len(response_data), 0)
