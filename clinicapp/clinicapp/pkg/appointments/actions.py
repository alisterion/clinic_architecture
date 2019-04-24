from datetime import timedelta, time, datetime

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import GEOSGeometry
from django.db.models import (
    Q, Sum, Max, Case, When, F, Min, DateTimeField, IntegerField, Value
)
from django.db.transaction import atomic
from django.utils.timezone import now as tz_now
from psycopg2.extras import DateTimeTZRange
from rest_framework.exceptions import ValidationError

from clinicapp.pkg.appointments.choices import (
    AppointmentClinicState, AppointmentState
)
from clinicapp.pkg.appointments.filters import (
    filter_by_location, filter_by_treatments, filter_clinics_which_reject,
    filter_clinics_which_suggested, filter_clinics_online
)
from clinicapp.pkg.appointments.models import (
    AppointmentClinicEvent, AppointmentSchedule
)
from clinicapp.pkg.appointments.serializers import (
    AppointmentClinicEventSerializer, AppointmentSerializer,
    AppointmentClinicWithSuggestionsSerializer,
    AppointmentAutomaticSuggestionsSerializer
)
from clinicapp.pkg.clinics.choices import ClinicState
from clinicapp.pkg.clinics.models import Clinic
from clinicapp.pkg.common.choices import ChannelType
from clinicapp.pkg.common.utils import dt_combine
from clinicapp.pkg.notifications.choices import UserNotificationState
from clinicapp.pkg.notifications.messages import (
    AdminAcceptPushMessage,
    AdminSuggestPushMessage,
    PaymentAcceptedPushMessage)
from clinicapp.pkg.notifications.messenger import (
    SerializedMessenger,
    GroupSerializedMessenger,
    PushNotificationMessenger,
)
from clinicapp.pkg.notifications.models import UserNotification

User = get_user_model()


class AppointmentClinicSearcher(object):
    MAX_DAYS_DELTA = 10
    MAX_TIME_SLOTS_FOR_DAY = 3
    MAX_SUGGESTIONS = 5
    DAY_HOURS = 24
    SLOTS_FREE_PERCENT = 0.20
    TIME_SLOT_KEYWORD = 'time'

    clinic_filters = [
        filter_by_treatments, filter_by_location,
        filter_clinics_which_reject, filter_clinics_which_suggested,
    ]
    additional_clinic_filters = [
        filter_clinics_online,
    ]

    def __init__(self, treatments, longitude=None, latitude=None,
                 appointment=None, raise_exception=True,
                 use_additional_filters=False):
        """

        :param treatments: list of Treatments
        :param longitude: float or None
        :param latitude: float or None
        :param appointment: Appointment or None
        :param raise_exception: bool - will raised Validation error,
        if no clinics founds
        :param use_additional_filters: bool - if need filter clinics
        with additional filters
        :return:
        """
        self._treatments = treatments
        self._point = GEOSGeometry(
            'POINT(%s %s)' % (longitude, latitude), srid=4326
        ) if (longitude and latitude) else None
        self._appointment = appointment
        self.raise_exception = raise_exception

        self.clinics = Clinic.objects.select_related('admin').filter(
            status=ClinicState.Approved.value, admin__is_active=True)
        for clinic_filter in self.clinic_filters:
            self.clinics = clinic_filter(self.clinics, self)

        if use_additional_filters:
            for clinic_filter in self.additional_clinic_filters:
                self.clinics = clinic_filter(self.clinics, self)

    def get_treatments(self):
        """

        :return: list of Treatments
        """
        return self._treatments.all()

    def get_geo_point(self):
        """

        :return: GEOSGeometry instance
        """
        return self._point

    def get_appointment(self):
        """

        :return: Appointment
        """
        return self._appointment

    def get_clinics(self):
        """

        :return: Clinic QuerySet
        """
        return self.clinics

    def _get_suggestions_date(self):
        """
        Returned dates before and after selected date for appointment
        :return: GeneratorTypes:
        """
        expected_date = self._appointment.date_time.replace(hour=0, minute=0)
        for i in range(self.MAX_DAYS_DELTA):
            if i % 2 == 0:
                d = expected_date + timedelta(days=i//2)
                if d > tz_now():
                    yield d
            else:
                d = expected_date - timedelta(days=i//2 + 1)
                if d > tz_now():
                    yield d

    def _get_available_doctors_for(self, date):
        return User.objects.filter(
            doctor__clinic__in=self.clinics,
            doctor__schedules__day_of_week=date.weekday()
        )

    def _annotate_doctors_schedules(self, doctors, date):
        return doctors.annotate(
            work_from=Max(
                Case(
                    When(
                        doctor__schedules__day_of_week=date.weekday(),
                        then=date.date() + F('doctor__schedules__work_from')
                    ),
                    default=dt_combine(date, time(0, 0)),
                    output_field=DateTimeField()
                )
            ),
            work_to=Min(
                Case(
                    When(
                        doctor__schedules__day_of_week=date.weekday(),
                        then=date.date() + F('doctor__schedules__work_to')
                    ),
                    default=dt_combine(date, time(23, 59)),
                    output_field=DateTimeField()
                )
            ),
            appoitment_date_time=Value(
                self._appointment.date_time, output_field=DateTimeField()
            )
        )

    def _get_time_conditions_for(self, date):
        """
        Split day by timing slots and compose conditions
        for calculating workload for each slot
        :param date:
        :return:
        """
        conditions = {}
        for hour in range(self.DAY_HOURS):
            start = dt_combine(date.date(), time(hour, 0))
            if hour != self.DAY_HOURS - 1:
                end = dt_combine(date.date(), time(hour + 1, 0))
            else:
                end = dt_combine(
                    (date + timedelta(days=1)).date(), time(0, 0)
                )
            conditions['%s%s' % (self.TIME_SLOT_KEYWORD, hour)] = Sum(
                Case(
                    When(
                        Q(appointment_schedules__duration__overlap=
                          DateTimeTZRange(start, end)) |
                        Q(work_from__gte=end) |
                        Q(work_to__lte=start) |
                        Q(appoitment_date_time__range=(start, end)),
                        then=1
                    ),
                    default=0, output_field=IntegerField()
                )
            )
        return conditions

    def get_time_slots_for(self, date: datetime):
        """

        :param date: datetime
        :return: iterable of tuples
        """
        doctors = self._get_available_doctors_for(date)
        doctors_cnt = int(doctors.count())
        if doctors_cnt == 0:
            return []
        doctors = self._annotate_doctors_schedules(doctors, date)
        # slots is dict, example - {'time0': 10, 'time1': 8, ...}
        slots = doctors.aggregate(**self._get_time_conditions_for(date))
        # for some time slots not any information about workload
        slots = filter(lambda item: item[1] is not None, slots.items())
        slots = map(lambda item: (item[0], (item[1] or 0)/doctors_cnt), slots)
        slots = filter(lambda item: item[1] < self.SLOTS_FREE_PERCENT, slots)
        return sorted(slots, key=lambda item: (item[1], item[0]))

    def _get_time_from(self, description: str):
        """

        :param description: str - 'time12'
        :return: time
        """
        hour = int(description.split(self.TIME_SLOT_KEYWORD)[-1])
        return time(hour, 0)

    def get_suggestions_time(self):
        if not self._appointment:
            return []
        result = []
        for date in self._get_suggestions_date():
            result.extend(
                [
                    (weight, date, self._get_time_from(hour))
                    for hour, weight in self.get_time_slots_for(date)
                ][:self.MAX_TIME_SLOTS_FOR_DAY]
            )

        # sorting by date, time
        result.sort(key=lambda x: (x[1], x[2]))

        suggestions = []
        for _, _date, _time in result[:self.MAX_SUGGESTIONS]:
            suggestions.append({
                'date': _date.date(),
                'time': _time
            })
        return suggestions


class AppointmentActions(object):

    APPOINTMENT_CREATE_ACTION = 'appointment_created'
    APPOINTMENT_CANCELED = 'appointment_canceled'
    APPOINTMENT_INACTIVE = 'appointment_inactive'
    APPOINTMENT_ACCEPTED_BY_ADMIN = 'appointment_clinic_accept'
    APPOINTMENT_SUGGESTED_BY_ADMIN = 'appointment_clinic_suggested'
    APPOINTMENT_USER_REJECT_SUGGESTION = 'appointment_user_reject_suggestions'
    APPOINTMENT_USER_ACCEPT_SUGGESTION = 'appointment_user_accept_suggestion'
    APPOINTMENT_TIMEOUT = 'appointment_timeout_expired'
    APPOINTMENT_RESCHEDULE_ACTION = 'appointment_rescheduled'
    APPOINTMENT_CONFIRMED = "appointment_confirmed"

    def __init__(self, appointment, is_support_admin_time=False):
        self._appointment = appointment
        self.is_support_admin_time = is_support_admin_time

    def open(self, clinics):
        """

        :param clinics: Clinic QuerySet
        :return:
        """
        events = []
        for clinic in clinics:
            events.append(AppointmentClinicEvent(
                appointment=self._appointment,
                clinic=clinic
            ))
        support_admin_events = []
        for event in AppointmentClinicEvent.objects.bulk_create(events):
            if self.is_support_admin_time:
                support_admin_events.append(event)
            else:
                self.send_created(event)
        if support_admin_events:
            self.send_created_group(support_admin_events)

    def reject(self, event):
        """

        :param event: AppointmentClinicEvent instance
        :return:
        """

        if not self._appointment.is_opened or not event.is_opened:
            raise ValidationError(
                "You can not reject appointment in status %s, "
                "and event in status %s" % (
                    self._appointment.status_description,
                    event.status_description
                )
            )
        # Change status to Rejected in event, when status still Created
        event.set_reject()

        # If some notification leaving for this clinic's admin,
        # change their status to Canceled
        self._cancel_pending_notifications(user_id=event.clinic.admin_id)

    @atomic()
    def accept(self, event):
        """

        :param event: AppointmentClinicEvent instance
        :return:
        """

        if not self._appointment.is_opened or not event.is_opened:
            raise ValidationError(
                "You can not accept appointment in status %s, "
                "and event in status %s" % (
                    self._appointment.status_description,
                    event.status_description
                )
            )

        # appointment status changed to Reserved
        self._appointment.set_reserved(event.clinic)
        # event for current clinic change status to Accept
        event.set_accept()
        other_events = self._appointment.events.filter(
            status=AppointmentClinicState.Active.value)
        other_events_pk = list(other_events.values_list('pk', flat=True))

        # status for other clinic events change to Inactive
        other_events.update(status=AppointmentClinicState.Inactive.value)

        # Create schedule for doctor and appointment
        AppointmentSchedule.create_from(self._appointment)

        # admins from other clinics receive
        # notification about inactive appointment
        support_admin_events = []
        for e in self._appointment.events.filter(pk__in=other_events_pk):
            if self.is_support_admin_time:
                support_admin_events.append(e)
            else:
                self.send_inactive(e)
        if support_admin_events:
            self.send_inactive_group(support_admin_events)

        # patient receive notification about accept
        self.send_accepted(event)

        self._cancel_pending_notifications()

    @atomic()
    def confirm(self, event):
        if not self._appointment.is_reserved:
            raise ValidationError(
                "You can not book appointment in status {}".format(
                    self._appointment.status_description
                )
            )
        self._appointment.set_confirmed()
        self._appointment.basket.set_status_payed()
        self.send_confirmed(event)
        self.send_confirmed_to_user()

    @atomic()
    def suggest(self, event):
        """

        :param event: AppointmentClinicEvent instance
        :return:
        """

        if not self._appointment.is_opened or not event.is_opened:
            raise ValidationError(
                "You can not add suggestions to appointment in status %s "
                "and event in status %s" % (
                    self._appointment.status_description,
                    event.status_description
                )
            )

        # appointment status changed to WaitingForUserDecide
        self._appointment.set_wait_for_user()
        # event for current clinic change status to Suggested
        event.set_suggested()

        other_events = self._appointment.events.exclude(pk=event.pk)

        # status for other clinic events change to Inactive
        other_events.filter(status=AppointmentClinicState.Active.value)\
            .update(status=AppointmentClinicState.Inactive.value)

        # admins from other clinics receive
        # notification about inactive appointment
        other_group_events = []
        for e in other_events:
            if self.is_support_admin_time:
                other_group_events.append(e)
            else:
                self.send_inactive(e)
        if other_group_events:
            self.send_inactive_group(other_group_events)

        # patient receive notification about accept
        self.send_suggested(event)

        self._cancel_pending_notifications()

    @atomic()
    def reject_suggestions(self, event):
        """

        :param event: AppointmentClinicEvent
        :return:
        """
        if not self._appointment.is_waiting_for_user or not event.is_suggested:
            raise ValidationError(
                "You can not reject suggestions to appointment in status %s "
                "and event in status %s" % (
                    self._appointment.status_description,
                    event.status_description
                )
            )

        # appointment status changed to UserRejectSuggestions
        self._appointment.set_reject_suggestions()

        # all suggestions for current event not chosen
        event.suggestions.update(is_chosen=False)
        event.set_rejected_suggestions()

        # send notification to admin
        if self.is_support_admin_time:
            self.send_user_reject_suggestions_group(event)
        else:
            self.send_user_reject_suggestions(event)

    @atomic()
    def accept_suggestion(self, event, suggestion):
        if not self._appointment.is_waiting_for_user or not event.is_suggested:
            raise ValidationError(
                "You can not reject suggestions to appointment in status %s "
                "and event in status %s" % (
                    self._appointment.status_description,
                    event.status_description
                )
            )

        suggestion.chose()

        # Create schedule for doctor and appointment
        AppointmentSchedule.create_from(self._appointment)
        if self.is_support_admin_time:
            self.send_user_accept_suggestion_group(event)
        else:
            self.send_user_accept_suggestion(event)

    @atomic()
    def cancel(self, raise_if_no_refund=True, notif_user=False):
        # User can cancel appointment
        if self._appointment.status == AppointmentState.Canceled.value:
            raise ValidationError({"detail": "Appointment already canceled."})

        if self._appointment.status == AppointmentState.Confirmed.value:
            raise ValidationError(
                {"detail": "You can not cancel appointment, "
                           "it already confirmed. "
                           "Please contact with administrator"}
            )

        # canceled appointment
        self._appointment.set_canceled()
        self._appointment.basket.set_status_canceled()
        events = self._appointment.events.all()

        # set inactive all active events for clinics
        active_events = events.filter(
            status__lte=AppointmentClinicState.Suggested.value
        )
        active_events_list = list(active_events)
        active_events.update(status=AppointmentClinicState.Inactive.value)

        # send notification about inactive appointment to admins
        active_events_group = []
        for event in active_events_list:
            if self.is_support_admin_time:
                active_events_group.append(event)
            else:
                self.send_canceled(event)
        if active_events_group:
            self.send_canceled_group(active_events_group)

        if notif_user:
            self.send_canceled_to_user()

        self._cancel_pending_notifications()

        # Delete schedule for canceled appointment
        AppointmentSchedule.objects.filter(
            appointment=self._appointment).delete()

    def refund(self, raise_if_no_refund=True):
        delta = self._appointment.date_time - tz_now()
        if delta > timedelta(days=3):
            # TODO: add refund
            # When appointment already booked it's mean that was payment
            # and need to refund half of amount
            raise NotImplementedError

        if raise_if_no_refund:
            raise ValidationError(
                "Cannot refund money %d days before appointment" % delta.days
            )

    @atomic()
    def timeout(self, suggestions=None):
        if self._appointment.status != AppointmentState.Opened.value:
            return

        self._appointment.set_timeout()

        events = self._appointment.events.all()

        active_events = events.filter(
            status=AppointmentClinicState.Active.value)
        active_events_list = list(active_events)
        active_events.update(status=AppointmentClinicState.Inactive.value)

        active_events_group = []
        for e in active_events_list:
            if self.is_support_admin_time:
                active_events_group.append(e)
            else:
                self.send_timeout_admin(e)
        if active_events_group:
            self.send_timeout_admin_group(active_events_group)
        self._cancel_pending_notifications()

        self.send_timeout_user(suggestions)

    @atomic()
    def reopen(self, clinics):
        """

        :param clinics: Clinic QuerySet
        :return:
        """
        if self._appointment.status not in [
            AppointmentState.UserRejectSuggestions,
            AppointmentState.TimeOut
        ]:
            raise ValidationError(
                "You can not reopen request for appointment in status %s"
                % self._appointment.status_description
            )

        self._appointment.set_opened()

        existing_events_pk = list(self._appointment.events.filter(
            clinic__in=clinics).values_list('pk', flat=True))

        AppointmentClinicEvent.objects.filter(pk__in=existing_events_pk).\
            update(status=AppointmentClinicState.Active.value)

        AppointmentClinicEvent.objects.bulk_create([
            AppointmentClinicEvent(
                appointment=self._appointment,
                clinic=clinic
            ) for clinic in clinics.exclude(
                appointment_events__pk__in=existing_events_pk)
        ])

        for event in self._appointment.events.filter(
                status=AppointmentClinicState.Active.value):
            self.send_created(event)

    def _cancel_pending_notifications(self, **params):
        # TODO: Maybe some clinic receive notification about create
        # and at canceled appointment admin is offline,
        # in this way notification about canceling will be canceled

        # If some notification leaving for clinic's admin,
        # change their status to Canceled
        UserNotification.objects.filter(
            user__self_clinic__appointment_events__appointment=
            self._appointment,
            user__self_clinic__appointment_events__status__gte=
            AppointmentClinicState.Rejected.value,
            status=UserNotificationState.Pending.value, **params
        ).exclude(user_id=self._appointment.patient_id).update(
            status=UserNotificationState.Canceled.value)

    @staticmethod
    def send_to_admin(action, admin, app_clinic_event, appointment):
        SerializedMessenger(
            group_name=ChannelType.UserPrivate.value % admin.id,
            action=action,
            serializer=AppointmentClinicEventSerializer,
            instance=app_clinic_event,
            obj_name='appointment_event',
            user=admin, appointment=appointment
        ).send()

    @staticmethod
    def send_to_admin_group(action, app_clinic_events, appointment):
        for admin in User.objects.support_admins():
            GroupSerializedMessenger(
                group_name=admin.get_personal_channel(),
                action=action,
                serializer=AppointmentClinicEventSerializer,
                instances=app_clinic_events,
                obj_name='appointment_event',
                appointment=appointment
            ).send()

    @staticmethod
    def send_to_user(action, user, appointment, event=None,
                     serializer=None, obj_name=None, push_message=None):
        SerializedMessenger(
            group_name=ChannelType.UserPrivate.value % user.id,
            action=action,
            serializer=serializer or AppointmentClinicEventSerializer,
            instance=event or appointment,
            obj_name=obj_name or 'appointment_event',
            user=user, appointment=appointment,
            push_message=push_message,
            push_if_only_offline=bool(push_message)
        ).send()

    def send_created(self, event):
        self.send_to_admin(
            self.APPOINTMENT_CREATE_ACTION, event.clinic.admin,
            event, self._appointment
        )

    def send_created_group(self, events):
        self.send_to_admin_group(
            self.APPOINTMENT_CREATE_ACTION,
            events, self._appointment
        )

    def send_canceled(self, event):
        self.send_to_admin(
            self.APPOINTMENT_CANCELED, event.clinic.admin,
            event, self._appointment
        )

    def send_canceled_group(self, events):
        self.send_to_admin_group(
            action=self.APPOINTMENT_CANCELED,
            app_clinic_events=events,
            appointment=self._appointment
        )

    def send_canceled_to_user(self):
        self.send_to_user(
            self.APPOINTMENT_CANCELED, self._appointment.patient,
            self._appointment, serializer=AppointmentSerializer,
            obj_name='appointment'
        )

    def send_inactive(self, event):
        self.send_to_admin(
            self.APPOINTMENT_INACTIVE, event.clinic.admin,
            event, self._appointment
        )

    def send_inactive_group(self, events):
        self.send_to_admin_group(
            action=self.APPOINTMENT_INACTIVE,
            app_clinic_events=events,
            appointment=self._appointment
        )

    def send_accepted(self, event):
        self.send_to_user(
            self.APPOINTMENT_ACCEPTED_BY_ADMIN,
            self._appointment.patient, self._appointment, event,
            push_message=AdminAcceptPushMessage()
        )

    def send_confirmed(self, event):
        self.send_to_admin(
            self.APPOINTMENT_CONFIRMED,
            event.clinic.admin,
            event,
            self._appointment
        )

    def send_confirmed_to_user(self):
        PushNotificationMessenger.send(
            self._appointment.patient,
            PaymentAcceptedPushMessage(),
            show_in_list=True
        )

    def send_suggested(self, event):
        self.send_to_user(
            self.APPOINTMENT_SUGGESTED_BY_ADMIN,
            self._appointment.patient, self._appointment, event,
            AppointmentClinicWithSuggestionsSerializer,
            push_message=AdminSuggestPushMessage()
        )

    def send_user_reject_suggestions(self, event):
        self.send_to_admin(
            self.APPOINTMENT_USER_REJECT_SUGGESTION,
            event.clinic.admin, event, self._appointment
        )

    def send_user_reject_suggestions_group(self, event):
        self.send_to_admin_group(
            action=self.APPOINTMENT_USER_REJECT_SUGGESTION,
            app_clinic_events=event,
            appointment=self._appointment
        )

    def send_user_accept_suggestion(self, event):
        self.send_to_admin(
            self.APPOINTMENT_USER_ACCEPT_SUGGESTION,
            event.clinic.admin, event, self._appointment
        )

    def send_user_accept_suggestion_group(self, event):
        self.send_to_admin_group(
            action=self.APPOINTMENT_USER_ACCEPT_SUGGESTION,
            app_clinic_events=event,
            appointment=self._appointment
        )

    def send_timeout_admin(self, event):
        self.send_to_admin(
            self.APPOINTMENT_TIMEOUT, event.clinic.admin,
            event, self._appointment
        )

    def send_timeout_admin_group(self, events):
        self.send_to_admin_group(
            action=self.APPOINTMENT_TIMEOUT,
            app_clinic_events=events,
            appointment=self._appointment
        )

    def send_timeout_user(self, suggestions):
        appointment = self._appointment
        appointment.suggestions = suggestions or[]
        self.send_to_user(
            self.APPOINTMENT_TIMEOUT, appointment.patient, appointment,
            serializer=AppointmentAutomaticSuggestionsSerializer,
            obj_name='appointment',
        )
