from datetime import timedelta

from django.utils.timezone import now as tz_now
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase

from clinicapp.pkg.appointments.choices import AppointmentState
from clinicapp.pkg.appointments.models import AppointmentRating
from clinicapp.pkg.clinics.choices import ClinicState
from clinicapp.pkg.users.services.user_service import GroupService
from clinicapp.tests.utils import UserRecipe, ClinicRecipe, \
    AppointmentRecipe, AppointmentRatingRecipe


class TestAppointmentRating(APITestCase):

    api_rating_pattern = 'appointment-rating'

    def setUp(self):
        self._prepare_users()
        self._prepare_clinics()
        self._prepare_appointments()
        self._prepare_ratings()

    def _prepare_users(self):
        self.user = UserRecipe.make()
        self.client.force_login(self.user)
        self.clinic_admin = UserRecipe.make()
        self.clinic_admin.groups.add(GroupService.get_clinics_admin())
        self.super_admin = UserRecipe.make()
        self.super_admin.groups.add(GroupService.get_super_admin())

    def _prepare_clinics(self):
        self.clinic = ClinicRecipe.make(status=ClinicState.Approved.value,
                                        admin=self.clinic_admin)

    def _prepare_appointments(self):
        self.appointment = AppointmentRecipe.make(
            patient=self.user, status=AppointmentState.Confirmed.value,
            clinic=self.clinic, date_time=tz_now() - timedelta(days=20),
        )
        self.appointment1 = AppointmentRecipe.make(
            patient=self.user, status=AppointmentState.Confirmed.value,
            clinic=self.clinic, date_time=tz_now() - timedelta(days=20),
        )
        self.upcoming_appointment = AppointmentRecipe.make(
            patient=self.user, status=AppointmentState.Confirmed.value,
            clinic=self.clinic, date_time=tz_now() + timedelta(days=2)
        )
        self.other_appointment = AppointmentRecipe.make(
            status=AppointmentState.Confirmed.value)

    def _prepare_ratings(self):
        self.rating = AppointmentRatingRecipe.make(
            appointment=self.appointment, rate=5)
        for _ in range(3):
            AppointmentRatingRecipe.make(
                appointment=AppointmentRecipe.make(_fill_optional=['clinic'])
            )

    def _get_data(self, **kwargs):
        data = {
            'rate': 5,
            'comment': 'Everything is ok'
        }
        data.update(**kwargs)
        return data

    def test_user_retrieve_rating_response_200(self):
        r = self.client.get(
            reverse(self.api_rating_pattern, [self.appointment.id]))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertIn('appointment', response_data)

    def test_user_add_rate_for_appointment_response_200(self):
        data = self._get_data()
        r = self.client.post(reverse(self.api_rating_pattern,
                                     [self.appointment1.id]), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(response_data['rate'], 5, response_data)

    def test_user_update_rate_for_appointment_response_200(self):
        data = self._get_data()
        r = self.client.post(reverse(self.api_rating_pattern,
                                     [self.appointment.id]), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(response_data['rate'], 5, response_data)

    def test_user_cant_add_rate_for_upcoming_appointment_response_404(self):
        data = self._get_data()
        r = self.client.post(reverse(self.api_rating_pattern,
                                     [self.upcoming_appointment.id]), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 404, response_data)
        self.assertTrue(response_data)

    def test_user_cant_add_rate_for_foreign_appointment_response_404(self):
        data = self._get_data()
        r = self.client.post(reverse(self.api_rating_pattern,
                                     [self.other_appointment.id]), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 404, response_data)
        self.assertTrue(response_data)

    def test_user_add_bad_params_for_rate_return_bad_request_400(self):
        data = {'rate': -465.4}
        r = self.client.post(reverse(self.api_rating_pattern,
                                     [self.appointment1.pk]), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 400, response_data)
        self.assertIn('comment', response_data)
        self.assertIn('rate', response_data)

    def test_user_update_rate_response_200(self):
        data = {'rate': 2, 'comment': 'bad'}
        r = self.client.post(reverse(self.api_rating_pattern,
                                     [self.appointment1.id]), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(response_data['rate'], 2, response_data)
        self.assertEquals(response_data['comment'], 'bad', response_data)

    def test_user_delete_rating(self):
        r = self.client.delete(reverse(self.api_rating_pattern,
                                       [self.appointment.id]))
        self.assertEquals(r.status_code, 204)
        self.assertFalse(
            AppointmentRating.objects.filter(
                appointment_id=self.appointment.id).exists()
        )

    def test_user_cant_delete_not_existing_rating(self):
        r = self.client.delete(reverse(self.api_rating_pattern,
                                       [self.appointment1.id]))
        response_data = r.json()
        self.assertEquals(r.status_code, 404, response_data)
        self.assertTrue(response_data)

    def test_user_cant_see_list_of_ratings_response_403(self):
        r = self.client.get(reverse(self.api_rating_pattern + '-list'))
        response_data = r.json()
        self.assertEquals(r.status_code, 403, response_data)
        self.assertTrue(response_data)

    def test_super_admin_get_list_rating_response_200(self):
        self.client.force_login(self.super_admin)
        r = self.client.get(reverse(self.api_rating_pattern + '-list'))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(len(response_data), 4, response_data)

    def test_clinic_admin_get_list_ratings_response_200(self):
        self.client.force_login(self.clinic_admin)
        r = self.client.get(reverse(self.api_rating_pattern + '-list'))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(response_data['count'], 1, response_data)

    def test_user_add_rate_clinic_rating_is_updated(self):
        self.clinic.refresh_from_db()
        rate_before = float(self.clinic.sum_rating)
        cnt_before = int(self.clinic.cnt_rating)

        data = self._get_data(rate=5)
        r = self.client.post(reverse(self.api_rating_pattern,
                                     [self.appointment1.id]), data)
        response_data = r.json()
        self.clinic.refresh_from_db()

        rate_after = float(self.clinic.sum_rating)
        cnt_after = int(self.clinic.cnt_rating)
        self.assertEquals(rate_before + 5, rate_after, response_data)
        self.assertEquals(cnt_before + 1, cnt_after, response_data)

    def test_user_change_rate_clinic_rating_is_updated(self):
        self.clinic.refresh_from_db()
        rate_before = float(self.clinic.sum_rating)
        cnt_before = int(self.clinic.cnt_rating)

        data = self._get_data(rate=2)
        r = self.client.post(reverse(self.api_rating_pattern,
                                     [self.appointment.id]), data)
        response_data = r.json()
        self.clinic.refresh_from_db()

        rate_after = float(self.clinic.sum_rating)
        cnt_after = int(self.clinic.cnt_rating)
        self.assertEquals(rate_before - 5 + 2, rate_after, response_data)
        self.assertEquals(cnt_before, cnt_after, response_data)

    def test_user_delete_rate_clinic_rating_is_updated(self):
        self.clinic.refresh_from_db()
        rate_before = float(self.clinic.sum_rating)
        cnt_before = int(self.clinic.cnt_rating)

        r = self.client.delete(reverse(self.api_rating_pattern,
                                       [self.appointment.id]))
        self.clinic.refresh_from_db()

        rate_after = float(self.clinic.sum_rating)
        cnt_after = int(self.clinic.cnt_rating)
        self.assertEquals(rate_before - 5, rate_after, r.status_code)
        self.assertEquals(cnt_before - 1, cnt_after, r.status_code)
