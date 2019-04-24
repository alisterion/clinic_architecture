import json
from datetime import datetime, timedelta, time

from django.test import override_settings, mock
from django.utils.timezone import now as tz_now
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase

from clinicapp.pkg.appointments.actions import AppointmentActions
from clinicapp.pkg.appointments.choices import AppointmentClinicState, \
    AppointmentState
from clinicapp.pkg.appointments.models import (
    AppointmentClinicEvent,
    AppointmentSuggestion,
)
from clinicapp.pkg.clinics.choices import ClinicState
from clinicapp.pkg.users.choices import BasketStatus
from clinicapp.pkg.users.services.user_service import GroupService
from clinicapp.tests.appointments.base import AppointmentTestMixin
from clinicapp.tests.utils import (
    UserRecipe,
    ClinicRecipe,
    TreatmentRecipe,
)


@mock.patch('clinicapp.pkg.appointments.views.'
            'check_status_appointment_after_open')
@mock.patch('clinicapp.pkg.appointments.views.'
            'check_status_appointment_after_suggest')
@mock.patch('clinicapp.pkg.appointments.views.'
            'check_status_appointment_after_reserved')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True,
                   CELERY_ALWAYS_EAGER=True,
                   BROKER_BACKEND='memory')
class TestAppointmentsAPI(AppointmentTestMixin, APITestCase):

    def test_create_appointment_response_201(self, *args):
        code, response_data, _ = self._create_appointment()
        self.assertEquals(code, 201, response_data)
        self.assertIn('location', response_data)

    def test_create_appointment_in_far_from_clinic_response_400(self, *args):
        code, response_data, _ = self._create_appointment(longitude=50)
        self.assertEquals(code, 400, response_data)
        self.assertIn('location', response_data)

    def test_create_appointment_without_treatments_response_400(self, *args):
        code, response_data, _ = self._create_appointment(treatments=[])
        self.assertEquals(code, 400, response_data)
        self.assertEquals(response_data.get('non_field_errors')[0],
                          'Basket is empty')

    def test_create_appointment_with_past_date_response_400(self, *args):
        code, response_data, _ = self._create_appointment(date='2015-1-1')
        self.assertEquals(code, 400, response_data)
        self.assertIn('date', response_data)

    def test_create_appointment_with_past_time_response_400(self, *args):
        code, response_data, _ = self._create_appointment(
            date=str(tz_now().date()), time='0:0')
        self.assertEquals(code, 400, response_data)
        self.assertIn('time', response_data)

    def test_user_cant_create_appointment_with_not_full_profile_response_400(
            self, *args):
        self.simple_user.nric = ''
        self.simple_user.save()
        code, response_data, _ = self._create_appointment()
        self.assertEquals(code, 400, response_data)
        self.assertEquals(response_data['detail'][0],
                          'Please fill out the profile')

    def test_admin_cant_create_appointment(self, *args):
        self.client.force_login(self.clinic_admin1)
        code, response_data, _ = self._create_appointment()
        self.assertEquals(code, 403, response_data)

    def test_create_appointment_basket_is_empty(self, *args):
        self._create_appointment()
        r = self.client.get(reverse(self.api_pattern_basket+'-detail'))
        response_data = r.json()
        self.assertEquals(r.status_code, 200, response_data)
        self.assertEqual(response_data.get('treatments'), [])

    def test_create_appointment_events_for_clinics_created_too(self, *args):
        events_before = AppointmentClinicEvent.objects.count()
        self._create_appointment()
        events_after = AppointmentClinicEvent.objects.count()
        self.assertEquals(events_before + 2, events_after)

    def test_create_appointment_full_treatments_filtering_one_event_created(
            self, *args):
        treatments = TreatmentRecipe.make(_quantity=4)
        admins = UserRecipe.make(is_active=True, _quantity=2)
        clinic1 = ClinicRecipe.make(status=40, admin=admins[0])
        clinic1.treatments.add(*treatments)

        clinic2 = ClinicRecipe.make(status=40, admin=admins[1])
        clinic2.treatments.add(*treatments[1:])
        data = {
            'treatments': [t.id for t in treatments[0:3]],
            'date': str(tz_now().date() + timedelta(days=1)), 'time': '10:00'
        }
        events_before = AppointmentClinicEvent.objects.count()
        self._create_appointment(data)
        events_after = AppointmentClinicEvent.objects.count()
        self.assertEquals(events_before + 1, events_after)

    def test_create_appointment_events_in_status_created(self, *args):
        c, r, appointment = self._create_appointment()
        statuses = AppointmentClinicEvent.objects.filter(
            appointment=appointment).values_list('status', flat=True)
        self.assertTrue(
            all(map(
                lambda x: x == AppointmentClinicState.Active.value,
                statuses))
        )

    def test_cancel_appointment_response_200(self, *args):
        c, r, appointment = self._create_appointment()
        code, response_data, appointment = self._cancel_appointment(
            appointment.pk)
        self.assertEquals(code, 200, response_data)
        self.assertTrue(response_data)
        self.assertEquals(appointment.status, AppointmentState.Canceled.value)

    def test_cancel_appointment_basket_in_status_canceled(self, *args):
        c, r, appointment = self._create_appointment()
        code, response_data, appointment = self._cancel_appointment(
            appointment.pk)
        self.assertEquals(
            appointment.basket.status, BasketStatus.Canceled.value,
            appointment.basket.status_description
        )

    def test_can_not_cancel_appointment_2_times(self, *args):
        c, r, appointment = self._create_appointment()
        self._cancel_appointment(appointment.pk)
        code, response_data, _ = self._cancel_appointment(appointment.pk)
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_cancel_appointment_all_clinic_event_is_inactive(self, *args):
        c, r, appointment = self._create_appointment()
        self._cancel_appointment(appointment.pk)
        statuses = AppointmentClinicEvent.objects.filter(
            appointment=appointment).values_list('status', flat=True)
        self.assertTrue(
            all(map(
                lambda x: x == AppointmentClinicState.Inactive.value,
                statuses))
        )

    def test_admin_reject_appointment_response_200(self, *args):
        c, r, appointment = self._create_appointment()
        code, response_data, event = self._reject(
            appointment, self.clinic_admin1)
        self.assertEquals(event.status, AppointmentClinicState.Rejected.value)
        self.assertEquals(code, 200, response_data)
        self.assertIn('appointment', response_data)

    def test_admin_cant_reject_appointment_after_accept_response_400(
            self, *args):
        c, r, appointment = self._create_appointment()
        self._accept(appointment, self.clinic_admin1)
        code, response_data, event = self._reject(
            appointment, self.clinic_admin1)
        self.assertEquals(event.status, AppointmentClinicState.Accepted.value)
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_after_reject_admin_can_not_accept(self, *args):
        c, r, appointment = self._create_appointment()
        self._reject(appointment, self.clinic_admin1)
        code, response_data, event = self._accept(
            appointment, self.clinic_admin1, {})
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_admin_accept_appointment_response_200(self, *args):
        c, r, appointment = self._create_appointment()
        code, response_data, event = self._accept(
            appointment, self.clinic_admin1)
        self.assertEquals(code, 200, response_data)
        self.assertIn('appointment', response_data)
        self.assertEquals(event.status, AppointmentClinicState.Accepted.value)
        self.assertEquals(event.appointment.status,
                          AppointmentState.Reserved.value)

    def test_user_cancel_appointment_after_accepted_by_admin_response_200(
            self, *args):
        c, r, appointment = self._create_appointment()
        self._accept(appointment, self.clinic_admin1)

        self.assertTrue(appointment.schedule.id)

        code, response_data, appointment = self._cancel_appointment(
            appointment.pk)
        self.assertEquals(code, 200, response_data)
        self.assertFalse(getattr(appointment, 'schedule', False))

    def test_admin_accept_appointment_schedule_is_created(self, *args):
        c, r, appointment = self._create_appointment()
        code, r, event = self._accept(appointment, self.clinic_admin1)
        appointment = event.appointment
        self.assertEquals(appointment.schedule.doctor, appointment.doctor)
        self.assertEquals(appointment.schedule.duration.lower,
                          appointment.date_time)
        self.assertEquals(
            appointment.date_time + timedelta(minutes=self.treatment_duration),
            appointment.schedule.duration.upper
        )

    def test_admin_accept_appointment_without_doctor_response_400(self, *args):
        c, r, appointment = self._create_appointment()
        data = {'adjust_30_min': True, }
        code, response_data, event = self._accept(
            appointment, self.clinic_admin1, data)
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_admin_accept_appointment_other_clinic_event_is_inactive(
            self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._accept(appointment, self.clinic_admin1)
        statuses = appointment.events.exclude(
            pk=event.pk).values_list('status', flat=True)
        self.assertTrue(
            all(map(
                lambda x: x == AppointmentClinicState.Inactive.value,
                statuses))
        )

    def test_one_admin_accept_other_admin_can_not_accept(self, *args):
        c, r, appointment = self._create_appointment()
        self._accept(appointment, self.clinic_admin1)
        data = {'doctor': self.user_doctor2.pk, }
        code, response_data, event = self._accept(
            appointment, self.clinic_admin2, data)
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_one_admin_accept_event_from_other_clinic_not_found(self, *args):
        c, r, appointment = self._create_appointment()
        self.client.force_login(self.clinic_admin1)
        event = appointment.events.get(clinic__admin=self.clinic_admin2)
        r = self.client.post(
            reverse(self.api_pattern_event + '-accept', [event.pk]),
            {'doctor': self.user_doctor2.pk, }
        )
        response_data = r.json()
        self.assertEquals(r.status_code, 404, response_data)
        self.assertTrue(response_data)

    def test_admin_can_not_accept_event_with_doctor_from_another_clinic(
            self, *args):
        c, r, appointment = self._create_appointment()
        data = {'doctor': self.user_doctor2.pk, }
        code, response_data, event = self._accept(
            appointment, self.clinic_admin1, data)
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_admin_suggest_another_time_response_200(self, *args):
        c, r, appointment = self._create_appointment()
        code, response_data, event = self._suggest(
            appointment, self.clinic_admin1)
        self.assertEquals(code, 200, response_data)
        self.assertIn('suggestions', response_data)
        self.assertEquals(event.appointment.status,
                          AppointmentState.WaitingForUserDecide.value)
        self.assertEquals(event.status, AppointmentClinicState.Suggested.value)

    def test_admin_cant_suggest_after_reject_response_200(self, *args):
        c, r, appointment = self._create_appointment()
        self._reject(appointment, self.clinic_admin1)
        code, response_data, event = self._suggest(
            appointment, self.clinic_admin1)
        self.assertEquals(event.status, AppointmentClinicState.Rejected.value)
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_admin_suggest_another_time_without_doctor_response_400(
            self, *args):
        c, r, appointment = self._create_appointment()
        doctor_pk = self.user_doctor1.pk
        data = json.dumps({"suggestions": [
            {'date': '2017-04-25', 'time': '12:00'},
            {'doctor': doctor_pk, 'date': '2017-04-25', 'time': '13:00'},
            {'doctor': doctor_pk, 'date': '2017-04-27', 'time': '14:00'}
        ]})
        code, response_data, event = self._suggest(
            appointment, self.clinic_admin1, data)
        self.assertEquals(code, 400, response_data)
        self.assertIn('suggestions', response_data)

    def test_admin_suggest_one_suggestion_3time_response_400(self, *args):
        c, r, appointment = self._create_appointment()
        suggestions = [{'doctor': self.user_doctor1.pk, 'date': '2017-04-25',
                       'time': '13:00'}]*3
        data = json.dumps({"suggestions": suggestions})
        code, response_data, event = self._suggest(
            appointment, self.clinic_admin1, data)
        self.assertEquals(code, 400, response_data)
        self.assertIn('suggestions', response_data)

    def test_admin_suggest_another_time_only_one_suggestion_response_400(
            self, *args):
        c, r, appointment = self._create_appointment()
        doctor_pk = self.user_doctor1.pk
        data = json.dumps({"suggestions": [
            {'doctor': doctor_pk, 'date': '2017-04-27', 'time': '14:00'}
        ]})
        code, response_data, event = self._suggest(
            appointment, self.clinic_admin1, data)
        self.assertEquals(code, 400, response_data)
        self.assertIn('suggestions', response_data)

    def test_admin_suggested_appointment_other_clinic_event_is_inactive(
            self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._suggest(appointment, self.clinic_admin1)
        statuses = appointment.events.exclude(
            pk=event.pk).values_list('status', flat=True)
        self.assertTrue(
            all(map(
                lambda x: x == AppointmentClinicState.Inactive.value,
                statuses))
        )

    def test_user_reject_suggestions_response_200(self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._suggest(appointment, self.clinic_admin1)

        code, response_data, event = self._reject_suggestion(event)
        self.assertEquals(code, 200, response_data)
        self.assertIn('appointment', response_data)
        self.assertEquals(event.appointment.status,
                          AppointmentState.UserRejectSuggestions.value)
        self.assertEquals(event.status,
                          AppointmentClinicState.RejectedSuggestions.value)

    def test_admin_can_not_reject_suggestions_response_403(self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._suggest(appointment, self.clinic_admin1)
        r = self.client.post(
            reverse(self.api_pattern_event + '-reject-suggestions', [event.pk])
        )
        response_data = r.json()
        self.assertEquals(r.status_code, 403, response_data)
        self.assertTrue(response_data)

    def test_reject_suggestions_after_admin_reject_bad_response_400(
            self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._reject(appointment, self.clinic_admin1)

        code, response_data, event = self._reject_suggestion(event)
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)

    def test_accept_suggestion_response_200(self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._suggest(appointment, self.clinic_admin1)

        suggestion_id = r.get('suggestions')[0].get('id')
        code, response_data, event = self._accept_suggestion(
            event, suggestion_id)
        self.assertEquals(code, 200, response_data)
        self.assertIn('appointment', response_data)
        self.assertEquals(
            response_data['appointment'].get('status'), "Reserved")
        self.assertEquals(event.appointment.status,
                          AppointmentState.Reserved.value)

    def test_user_cant_accept_suggestion_after_canceling_response_400(
            self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._suggest(appointment, self.clinic_admin1)
        suggestion_id = r.get('suggestions')[0].get('id')
        self._cancel_appointment(appointment.pk)
        code, response_data, event = self._accept_suggestion(
            event, suggestion_id)
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)
        self.assertEquals(event.appointment.status,
                          AppointmentState.Canceled.value)
        self.assertEquals(event.status, AppointmentClinicState.Inactive.value)

    def test_accept_suggestion_schedule_is_created(self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._suggest(appointment, self.clinic_admin1)

        suggestion_id = r.get('suggestions')[0].get('id')
        code, response_data, event = self._accept_suggestion(
            event, suggestion_id)
        appointment = event.appointment
        self.assertEquals(appointment.schedule.doctor, appointment.doctor)
        self.assertEquals(appointment.schedule.duration.lower,
                          appointment.date_time)
        self.assertEquals(
            appointment.date_time + timedelta(minutes=self.treatment_duration),
            appointment.schedule.duration.upper
        )

    def test_accept_suggestion_add_info_from_it(self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._suggest(appointment, self.clinic_admin1)

        suggestion_id = r.get('suggestions')[0].get('id')
        c, r, event = self._accept_suggestion(event, suggestion_id)
        suggestion = AppointmentSuggestion.objects.get(
            pk=suggestion_id)
        appointment = event.appointment
        self.assertEquals(appointment.doctor, suggestion.doctor)
        self.assertEquals(appointment.date_time, suggestion.date_time)
        self.assertTrue(suggestion.is_chosen)

    def test_reopen_appointment_after_reject_suggestions(self, *args):
        c, r, appointment = self._create_appointment()
        c, r, event = self._suggest(appointment, self.clinic_admin1)

        self._reject_suggestion(event)

        code, response_data, appointment = self._reopen(appointment.pk)
        self.assertEquals(code, 200, response_data)
        self.assertIn('location', response_data)
        self.assertEquals(appointment.status, AppointmentState.Opened.value)

    def test_reopen_appointment_after_timeout_status_for_event_active(
            self, *args):
        c, r, appointment = self._create_appointment()
        AppointmentActions(appointment).timeout()
        c, r, appointment = self._reopen(appointment.pk)
        statuses = appointment.events.values_list('status', flat=True)
        self.assertTrue(
            all(map(
                lambda x: x == AppointmentClinicState.Active.value,
                statuses))
        )

    def test_user_cant_reopen_appointment_after_canceling_response_400(
            self, *args):
        c, r, appointment = self._create_appointment()
        self._cancel_appointment(appointment.pk)
        code, response_data, appointment = self._reopen(appointment.pk)
        self.assertEquals(code, 400, response_data)
        self.assertTrue(response_data)
        self.assertEquals(appointment.status, AppointmentState.Canceled.value)

    def test_reopen_after_creating_clinic_new_event_will_create(self, *args):
        c, r, appointment = self._create_appointment()
        AppointmentActions(appointment).timeout()

        admin = UserRecipe.make(email='clinic3@admin.com', is_active=True)
        admin.groups.add(GroupService.get_clinics_admin())
        clinic = ClinicRecipe.make(admin=admin, location=self.clinic_point1,
                                   status=ClinicState.Approved.value)
        clinic.treatments.add(self.treatment)
        c, r, appointment = self._reopen(appointment.pk)
        events = appointment.events.all()
        statuses = events.values_list('status', flat=True)
        self.assertEquals(events.count(), 3)
        self.assertTrue(
            all(map(
                lambda x: x == AppointmentClinicState.Active.value,
                statuses))
        )

    def test_reopen_appointment_clinics_excluded_response_400(self, *args):
        c, r, appointment = self._create_appointment()

        self._reject(appointment, self.clinic_admin1)

        c, r, event = self._suggest(appointment, self.clinic_admin2)

        self._reject_suggestion(event)

        code, response_data, appointment = self._reopen(appointment.pk)
        self.assertEquals(code, 400, response_data)
        self.assertIn('location', response_data)
        self.assertEquals(appointment.status,
                          AppointmentState.UserRejectSuggestions.value)

    def test_reopen_appointment_clinic_which_reject_status_still_reject(
            self, *args):
        c, r, appointment = self._create_appointment()

        self._reject(appointment, self.clinic_admin1)
        AppointmentActions(appointment).timeout()

        c, r, appointment = self._reopen(appointment.pk)
        self.assertEquals(
            appointment.events.get(clinic__admin=self.clinic_admin1).status,
            AppointmentClinicState.Rejected.value)
        self.assertEquals(
            appointment.events.get(clinic__admin=self.clinic_admin2).status,
            AppointmentClinicState.Active.value)

    def test_reopen_appointment_clinic_which_user_rejected_status_still_reject(
            self, *args):
        c, r, appointment = self._create_appointment()

        c, r, event = self._suggest(appointment, self.clinic_admin2)

        self._reject_suggestion(event)

        c, r, appointment = self._reopen(appointment.pk)

        self.assertEquals(
            appointment.events.get(clinic__admin=self.clinic_admin1).status,
            AppointmentClinicState.Active.value)
        self.assertEquals(
            appointment.events.get(clinic__admin=self.clinic_admin2).status,
            AppointmentClinicState.RejectedSuggestions.value)

    def test_admin_accept_appointment_after_reopening(self, *args):
        c, r, appointment = self._create_appointment()

        AppointmentActions(appointment).timeout()

        c, r, appointment = self._reopen(appointment.pk)
        code, response_data, event = self._accept(
            appointment, self.clinic_admin1)
        self.assertEquals(code, 200, response_data)
        self.assertTrue(response_data.get('appointment', {}).get('doctor'))
        self.assertEquals(event.appointment.status,
                          AppointmentState.Reserved.value)
        self.assertEquals(event.status, AppointmentClinicState.Accepted.value)
