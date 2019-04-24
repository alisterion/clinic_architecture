import random
from datetime import time, timedelta

from channels.tests import HttpClient, ChannelTestCase
from django.test import override_settings
from django.utils.timezone import now as tz_now
from rest_framework.authtoken.models import Token

from clinicapp.pkg.appointments.models import AppointmentSchedule, Appointment
from clinicapp.pkg.clinics.choices import ClinicState
from clinicapp.pkg.clinics.models import Doctor, Schedule
from clinicapp.pkg.common.services.online import OnlineService
from clinicapp.pkg.users.services.user_service import GroupService
from clinicapp.tests.appointments.base import AppointmentTestMixin
from clinicapp.tests.utils import UserRecipe, DoctorRecipe, \
    ScheduleRecipe, ClinicRecipe, TreatmentRecipe, BasketRecipe


@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True,
                   CELERY_ALWAYS_EAGER=True,
                   BROKER_BACKEND='memory')
class TestSystemFindClinic(AppointmentTestMixin, ChannelTestCase):

    def _prepare_users(self):
        self.simple_user = UserRecipe.make()
        self.client.force_login(self.simple_user)

        self.user_doctors = UserRecipe.make(_quantity=10)

    def _prepare_treatments(self):
        self.treatments = []
        for duration in [20, 30, 45, 60, 20, 30, 45, 60, 40, 50]:
            self.treatments.append(
                TreatmentRecipe.make(duration=duration)
            )

    def _prepare_clinics(self):
        self.clinics = []
        for i in range(5):
            admin = UserRecipe.make(is_active=True)
            admin.groups.add(GroupService.get_clinics_admin())
            clinic = ClinicRecipe.make(
                status=ClinicState.Approved.value, admin=admin
            )
            clinic.treatments.add(*self.treatments)

            self.clinics.append(clinic)

            # clinics are online
            client = HttpClient()
            client.send_and_consume(
                "websocket.connect",
                path="/?auth_token=%s" % self._get_token_for(admin)
            )

    def _prepare_doctors(self):
        schedules_hours_from = [8, 9, 10, 11, 12]
        schedules_hours_to = [17, 18, 19, 20]

        for user, clinic in zip(self.user_doctors, self.clinics*2):
            clinic.treatments.add(*self.treatments)
            doctor = DoctorRecipe.make(user=user, clinic=clinic)
            for day in range(7):
                doctor.schedules.add(
                    ScheduleRecipe.make(
                        day_of_week=day,
                        work_from=time(random.choice(schedules_hours_from), 0),
                        work_to=time(random.choice(schedules_hours_to), 0)
                    )
                )

    def _prepare_appointments(self):
        appointments_schedules = [
            (timedelta(days=1), time(10, 0)),
            (timedelta(days=2), time(12, 0)),
            (timedelta(days=3), time(14, 0)),
            (timedelta(days=4), time(11, 0)),
            (timedelta(days=5), time(9, 0)),
            (timedelta(days=6), time(8, 0)),
            (timedelta(days=1), time(15, 0)),
            (timedelta(days=2), time(16, 0)),
            (timedelta(days=3), time(12, 0)),
            (timedelta(days=4), time(10, 0)),
            (timedelta(days=3), time(9, 0)),
            (timedelta(days=2), time(13, 0)),
            (timedelta(days=1), time(15, 0)),
            (timedelta(days=0), time(17, 0)),
            (timedelta(days=1), time(12, 0)),
        ]

        for delta, _time in appointments_schedules:
            date_time = tz_now() + delta
            date_time = date_time.replace(hour=_time.hour)
            doctor = Doctor.objects.filter(
                schedules__day_of_week=date_time.weekday(),
                schedules__work_from__lte=_time,
            ).order_by('?').first() or Doctor.objects.first()

            basket = BasketRecipe.make(treatments=[random.choice(
                self.treatments)]*3)
            appointment = Appointment.objects.create(
                date_time=date_time, doctor=doctor.user,
                clinic=doctor.clinic, patient=self.simple_user, basket=basket
            )
            AppointmentSchedule.create_from(appointment)

    def setUp(self):
        self._prepare_users()
        self._prepare_treatments()
        self._prepare_clinics()
        self._prepare_doctors()
        self._prepare_appointments()

    def _get_token_for(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        return token

    def _receive_msg_about_timeout(self):
        client = HttpClient()
        client.send_and_consume(
            "websocket.connect",
            path="/?auth_token=%s" % self._get_token_for(self.simple_user)
        )
        return client.receive()['message']

    def test_no_clinics_online_list_of_suggestions_is_empty(self):
        OnlineService.clear_all()
        date_time = tz_now() + timedelta(days=1)
        data = dict(
            date=date_time.strftime('%Y-%m-%d'),
            time=date_time.strftime('%H:%M'),
            treatments=[t.id for t in self.treatments[:3]]
        )
        self._create_appointment(data)
        msg = self._receive_msg_about_timeout()
        self.assertEquals(len(msg['appointment']['suggestions']), 0)

    def test_appointment_finished_with_5_suggestions(self):
        date_time = (tz_now()+timedelta(days=3)).replace(
            hour=15, minute=0, second=0)
        data = dict(
            date=date_time.strftime('%Y-%m-%d'),
            time=date_time.strftime('%H:%M'),
            treatments=[t.id for t in self.treatments[:3]]
        )
        self._create_appointment(data)
        msg = self._receive_msg_about_timeout()
        self.assertEquals(len(msg['appointment']['suggestions']), 5)

    def test_appointment_selected_date_not_in_suggestions(self):
        date_time = (tz_now()+timedelta(days=3)).replace(
            hour=15, minute=0, second=0)
        data = dict(
            date=date_time.strftime('%Y-%m-%d'),
            time=date_time.strftime('%H:%M'),
            treatments=[t.id for t in self.treatments[:3]]
        )
        selected_date_time = {'date': date_time.strftime('%d/%m/%Y'),
                              'time': date_time.strftime('%H:%M:%S')}
        self._create_appointment(data)
        msg = self._receive_msg_about_timeout()
        self.assertNotIn(selected_date_time, msg['appointment']['suggestions'])

    def test_no_suggestions_on_day_where_schedules_not_present(self):
        date_time = (tz_now()+timedelta(days=3)).replace(
            hour=15, minute=0, second=0)
        Schedule.objects.filter(day_of_week=date_time.weekday()).delete()
        data = dict(
            date=date_time.strftime('%Y-%m-%d'),
            time=date_time.strftime('%H:%M'),
            treatments=[t.id for t in self.treatments[:3]]
        )
        selected_date = date_time.strftime('%d/%m/%Y')
        self._create_appointment(data)
        msg = self._receive_msg_about_timeout()
        suggested_dates = list(map(lambda x: x['date'],
                                   msg['appointment']['suggestions']))
        self.assertNotIn(selected_date, suggested_dates)
