import json
from datetime import timedelta

from django.contrib.gis.geos import GEOSGeometry
from django.utils.timezone import now as tz_now
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from clinicapp.pkg.appointments.models import Appointment, \
    AppointmentClinicEvent
from clinicapp.pkg.clinics.choices import ClinicState
from clinicapp.pkg.common.services.online import OnlineService
from clinicapp.pkg.users.services.user_service import GroupService
from clinicapp.tests.utils import UserRecipe, TreatmentRecipe, ClinicRecipe, \
    DoctorRecipe


class AppointmentTestMixin(object):
    api_pattern_appointment = 'appointment'
    api_pattern_event = 'appointment-event'
    api_pattern_basket = 'basket'

    def setUp(self):
        self._prepare_users()
        self._prepare_clinics()
        self._prepare_doctors()

    def tearDown(self):
        OnlineService.clear_all()

    def _prepare_users(self):
        self.clinic_admin1 = UserRecipe.make(
            email='clinic1@admin.com', is_active=True)
        self.clinic_admin1.groups.add(GroupService.get_clinics_admin())

        self.clinic_admin2 = UserRecipe.make(
            email='clinic2@admin.com', is_active=True)
        self.clinic_admin2.groups.add(GroupService.get_clinics_admin())

        self.client = APIClient()
        self.support_admin = UserRecipe.make(
            email="support@admin.com", is_active=True
        )
        self.support_admin.groups.add(GroupService.get_support_admin())
        self.simple_user = UserRecipe.make(email='test@user.com')
        self.client.force_login(self.simple_user)

    def _prepare_clinics(self):
        self.treatment_duration = 60
        self.treatment = TreatmentRecipe.make(duration=self.treatment_duration)

        self.clinic_point1 = GEOSGeometry(
            'POINT(%s %s)' % (20.005, 40.01), srid=4326)
        self.clinic_point2 = GEOSGeometry(
            'POINT(%s %s)' % (19.99, 40.002), srid=4326)

        self.test_clinic1 = ClinicRecipe.make(
            admin=self.clinic_admin1, location=self.clinic_point1,
            status=ClinicState.Approved.value)
        self.test_clinic2 = ClinicRecipe.make(
            admin=self.clinic_admin2, location=self.clinic_point2,
            status=ClinicState.Approved.value)
        self.test_clinic1.treatments.add(self.treatment)
        self.test_clinic2.treatments.add(self.treatment)

    def _prepare_doctors(self):
        self.user_doctor1 = UserRecipe.make(
            email='doctor1@user.com', is_active=True)
        self.user_doctor1.groups.add(GroupService.get_doctor())
        DoctorRecipe.make(
            user=self.user_doctor1, is_approved=True, clinic=self.test_clinic1)

        self.user_doctor2 = UserRecipe.make(
            email='doctor2@user.com', is_active=True)
        self.user_doctor2.groups.add(GroupService.get_doctor())
        DoctorRecipe.make(
            user=self.user_doctor2, is_approved=True, clinic=self.test_clinic2)

    def _get_data(self, **kwargs):
        data = {
            "longitude": 20.00,
            "latitude": 40.00,
            "treatments": [self.treatment.id, ],
            "date": str(tz_now().date() + timedelta(days=4)),
            "time": '12:50',
        }
        data.update(kwargs)
        return data

    def _get_suggestions(self):
        doctor_pk = self.user_doctor1.pk
        return json.dumps({"suggestions": [
            {'doctor': doctor_pk, 'date': '2017-04-25', 'time': '12:00'},
            {'doctor': doctor_pk, 'date': '2017-04-25', 'time': '13:00'},
            {'doctor': doctor_pk, 'date': '2017-04-27', 'time': '14:00'}
        ]})

    def _create_appointment(self, data=None, **kwargs):
        data = data or self._get_data(**kwargs)
        r = self.client.put(
            reverse(self.api_pattern_basket+'-detail'),
            data=json.dumps(dict(treatments=data.pop('treatments', []))),
            content_type='application/json'
        )
        r = self.client.post(
            reverse(self.api_pattern_appointment + '-list'),
            data=json.dumps(data),
            content_type='application/json')
        pk = r.json().get('id')
        return (
            r.status_code, r.json(), Appointment.objects.filter(pk=pk).first()
        )

    def _cancel_appointment(self, pk):
        self.client.force_login(self.simple_user)
        r = self.client.post(
            reverse(self.api_pattern_appointment + '-cancel', [pk]))
        return (
            r.status_code, r.json(), Appointment.objects.get(pk=pk)
        )

    def _accept(self, appointment, admin, data=None):
        self.client.force_login(admin)
        event = appointment.events.get(clinic__admin=admin)
        r = self.client.post(
            reverse(self.api_pattern_event + '-accept', [event.pk]),
            data or {'doctor': self.user_doctor1.pk}
        )
        return (
            r.status_code, r.json(),
            AppointmentClinicEvent.objects.get(pk=event.pk)
        )

    def _reject(self, appointment, admin):
        self.client.force_login(admin)
        event = appointment.events.get(clinic__admin=admin)
        r = self.client.post(
            reverse(self.api_pattern_event + '-reject', [event.pk])
        )
        return (
            r.status_code, r.json(),
            AppointmentClinicEvent.objects.get(pk=event.pk)
        )

    def _suggest(self, appointment, admin, data=None):
        self.client.force_login(admin)
        event = appointment.events.get(clinic__admin=admin)
        r = self.client.post(
            reverse(self.api_pattern_event + '-suggest', [event.pk]),
            data or self._get_suggestions(), content_type='application/json'
        )
        return (
            r.status_code, r.json(),
            AppointmentClinicEvent.objects.get(pk=event.pk)
        )

    def _reject_suggestion(self, event):
        self.client.force_login(self.simple_user)
        r = self.client.post(
            reverse(self.api_pattern_event + '-reject-suggestions', [event.pk])
        )
        return (
            r.status_code, r.json(),
            AppointmentClinicEvent.objects.get(pk=event.pk)
        )

    def _accept_suggestion(self, event, suggestion_id):
        self.client.force_login(self.simple_user)
        r = self.client.post(
            '/api/v1/appointments/events/%s/accept_suggestion/%s' %
            (event.pk, suggestion_id)
        )
        return (
            r.status_code, r.json(),
            AppointmentClinicEvent.objects.get(pk=event.pk)
        )

    def _reopen(self, appointment_pk):
        self.client.force_login(self.simple_user)
        r = self.client.post(
            reverse(self.api_pattern_appointment + '-reopen',
                    [appointment_pk]))
        return (
            r.status_code, r.json(), Appointment.objects.get(pk=appointment_pk)
        )
