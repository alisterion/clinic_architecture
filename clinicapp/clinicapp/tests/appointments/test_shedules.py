from datetime import timedelta

from django.test import override_settings
from django.utils.timezone import now as tz_now
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase

from clinicapp.pkg.appointments.actions import AppointmentActions
from clinicapp.pkg.clinics.choices import ClinicState
from clinicapp.pkg.users.services.user_service import GroupService
from clinicapp.tests.utils import UserRecipe, ClinicRecipe, TreatmentRecipe, \
    DoctorRecipe, AppointmentRecipe, AppointmentEventRecipe


@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True,
                   CELERY_ALWAYS_EAGER=True,
                   BROKER_BACKEND='memory')
class TestAppointmentSchedule(APITestCase):

    api_schedule_pattern = 'appointment-schedule'

    def setUp(self):
        self._prepare_users()
        self._prepare_clinics()
        self._prepare_doctors()
        self._prepare_appointments()

    def _prepare_users(self):
        self.clinic_admin = UserRecipe.make(email='clinic@admin.com')
        self.clinic_admin.groups.add(GroupService.get_clinics_admin())
        self.client.force_login(self.clinic_admin)
        self.clinic_admin2 = UserRecipe.make(email='clinic2@admin.com')
        self.clinic_admin2.groups.add(GroupService.get_clinics_admin())

    def _prepare_clinics(self):
        self.clinic = ClinicRecipe.make(status=ClinicState.Approved.value,
                                        admin=self.clinic_admin)
        self.treatment = TreatmentRecipe.make(duration=60)
        self.clinic.treatments.add(self.treatment)

    def _prepare_doctors(self):
        self.doctor = UserRecipe.make(email='doctor@test.com', is_active=True)
        self.doctor.groups.add(GroupService.get_doctor())
        self.doctor_info = DoctorRecipe.make(clinic=self.clinic,
                                             user=self.doctor)

    def _prepare_appointments(self):
        self.appointment = AppointmentRecipe.make(
            doctor=self.doctor, date_time=tz_now() + timedelta(days=1)
        )
        self.appointment.treatments.add(self.treatment)
        self.app_event = AppointmentEventRecipe.make(
            appointment=self.appointment, clinic=self.clinic)
        AppointmentActions(self.appointment).accept(self.app_event)

    def test_get_list_appointment_schedules(self):
        r = self.client.get(reverse(self.api_schedule_pattern + '-list'))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertIn('doctor', response_data['results'][0])

    def test_get_list_appointment_schedules_other_admin_can_not_see_info(self):
        self.client.force_login(self.clinic_admin2)
        r = self.client.get(reverse(self.api_schedule_pattern + '-list'))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertListEqual(response_data['results'], [], response_data)

    def test_filter_schedules_by_date(self):
        data = {
            'appointment_starts': str(tz_now().date()),
            'appointment_ends': str(tz_now().date() + timedelta(days=2))
        }
        r = self.client.get(reverse(self.api_schedule_pattern + '-list'), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(response_data['count'], 1, response_data)

    def test_filter_schedules_by_date_without_appointment_empty_response(self):
        data = {
            'appointment_starts': str(tz_now().date() - timedelta(days=10)),
            'appointment_ends': str(tz_now().date() - timedelta(days=2))
        }
        r = self.client.get(reverse(self.api_schedule_pattern + '-list'), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(response_data['results'], [], response_data)

    def test_filter_schedules_by_bad_dates_response_200(self):
        data = {
            'appointment_starts': 'dfdfadfadf',
            'appointment_ends': '6546546564555'
        }
        r = self.client.get(reverse(self.api_schedule_pattern + '-list'), data)
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEquals(response_data['count'], 1, response_data)
