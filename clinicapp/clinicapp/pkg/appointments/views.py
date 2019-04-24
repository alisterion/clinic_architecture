from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.transaction import atomic
from django.utils.timezone import now as tz_now
from django_filters.rest_framework import DjangoFilterBackend
from rest_condition import Or
from rest_framework import permissions, serializers, mixins, status
from rest_framework.decorators import detail_route, list_route
from rest_framework.exceptions import NotFound
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from clinicapp.pkg.appointments.actions import AppointmentActions
from clinicapp.pkg.appointments.filters import (
    AppointmentClinicEventFilter, AppointmentScheduleFilter,
    AppointmentUpcomingFilter, AppointmentPassFilter, AppointmentUserFilter,
    AppointmentBookedFilter, AppointmentRatingUserFilter,
    AppointmentStatusRatingFilter, AppointmentScheduleDateTimeFilter,
)
from clinicapp.pkg.appointments.models import (
    Appointment, AppointmentClinicEvent, AppointmentSuggestion,
    AppointmentSchedule, ReminderTime, AppointmentRating
)
from clinicapp.pkg.appointments.permissions import IsAuthorOfAppointment
from clinicapp.pkg.appointments.serializers import (
    AppointmentSerializer, AppointmentClinicEventSerializer,
    AppointmentClinicWithSuggestionsSerializer, AppointmentScheduleSerializer,
    AppointmentReminderSerializer,
    ReminderTimeSerializer, AppointmentRatingSerializer,
    AppointmentUpcomingHistorySerializer,
    AppointmentPassedHistorySerializer
)
from clinicapp.pkg.appointments.tasks import (
    check_status_appointment_after_open,
    check_status_appointment_after_suggest,
    check_status_appointment_after_reserved,
)
from clinicapp.pkg.appointments.utils import SupportAdminTime
from clinicapp.pkg.common.mixins import MultiSerializerViewSetMixin
from clinicapp.pkg.common.pagination import ViewPagination
from clinicapp.pkg.users.permissions import (
    IsClinicsAdmin, IsSuperAdmin, IsSimpleUser, IsDoctor,
)

User = get_user_model()


class AppointmentViewSet(MultiSerializerViewSetMixin, GenericViewSet,
                         mixins.CreateModelMixin):
    """
    Endpoint for create request for appointment.
    When creating an appointment, system search
    clinics by treatments and location,
    if no clinics will be return 400 Bad request,
    otherwise starts process looking for clinic.
    All admins will receive notification about appointment and such of them
    can reject/accept/add suggestions for appointment.
    """
    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    filter_backends = (AppointmentUserFilter,)
    custom_serializer_classes = {
        'cancel': serializers.Serializer,
        'rating': AppointmentRatingSerializer,
        'reminders': AppointmentReminderSerializer,
        'passed': AppointmentPassedHistorySerializer,
        'upcoming': AppointmentUpcomingHistorySerializer,
    }
    permission_classes = (
        permissions.IsAuthenticated, IsSimpleUser
    )
    lookup_value_regex = '[\d]+'

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.date_time < tz_now():
            serializer = AppointmentPassedHistorySerializer(instance)
        else:
            serializer = AppointmentUpcomingHistorySerializer(instance)
        return Response(serializer.data)

    @atomic()
    def perform_create(self, serializer):
        appointment = serializer.save()
        clinics = serializer.clinic_searcher.get_clinics()
        support_admin_time = SupportAdminTime()
        AppointmentActions(
            appointment,
            support_admin_time.is_support_admin_time
        ).open(clinics)
        check_status_appointment_after_open.apply_async(
            args=(appointment.id,),
            # after timeout starts search for suggestions date and time
            # and it will last more-less 1 second
            countdown=support_admin_time.countdown_open() - 1)

    @detail_route(methods=['post'], permission_classes=[IsAuthorOfAppointment])
    def cancel(self, request, **kwargs):
        """
        Endpoint for cancel appointment.

        Check if possible will raised refund half of money,
        otherwise appointment will cancel
        """
        appointment = self.get_object()
        AppointmentActions(
            appointment,
            SupportAdminTime().is_support_admin_time
        ).cancel(raise_if_no_refund=False)
        return Response(AppointmentSerializer(appointment).data)

    @detail_route(methods=['post'],
                  permission_classes=[IsAuthorOfAppointment])
    def reopen(self, request, pk=None):
        """
        Endpoint for reopen appointment.

        If none clinics accept request for appointment
        and timeout expired or user rejected appointment,
        user can reopen appointment.
        """
        appointment = self.get_object()
        sz = self.get_serializer(appointment, data=request.data, partial=True)
        sz.is_valid(raise_exception=True)
        support_admin_time = SupportAdminTime()
        with atomic():
            sz.save()
            clinics = sz.clinic_searcher.get_clinics()
            AppointmentActions(
                appointment,
                support_admin_time.is_support_admin_time
            ).reopen(clinics)
        check_status_appointment_after_open.apply_async(
            args=(appointment.id,),
            countdown=support_admin_time.countdown_open())
        return Response(sz.data)

    @list_route(methods=['get', ], filter_backends=[
        AppointmentUserFilter, AppointmentUpcomingFilter,
        AppointmentBookedFilter])
    def upcoming(self, request):
        """
        List of upcoming endpoints for current user
        """
        appointments = self.filter_queryset(self.queryset)
        sz = self.get_serializer(appointments, many=True)
        return Response(sz.data)

    @list_route(methods=['get', ], filter_backends=[
        AppointmentUserFilter, AppointmentPassFilter, AppointmentBookedFilter])
    def passed(self, request):
        """
        List of passed endpoints for current user
        """
        appointments = self.filter_queryset(self.queryset)
        sz = self.get_serializer(appointments, many=True)
        return Response(sz.data)

    @detail_route(methods=['post', 'get', 'delete', ],
                  permission_classes=[IsAuthorOfAppointment],
                  filter_backends=[
                      AppointmentStatusRatingFilter, AppointmentUserFilter])
    def rating(self, request, pk=None):
        """
        Endpoints for CRUD rating for appointment
        """
        appointment = self.get_object()
        appointment_rating = getattr(appointment, 'rating', None)
        if request.method == 'POST':
            data = request.data.copy()
            data.update({'appointment': appointment.id})
            sz = self.get_serializer(appointment_rating, data=data)
            sz.is_valid(raise_exception=True)
            appointment_rating = sz.save()
        if request.method == 'DELETE':
            try:
                appointment_rating.delete()
            except AttributeError:
                raise NotFound
            return Response(status=status.HTTP_204_NO_CONTENT)
        sz = self.get_serializer(appointment_rating)
        return Response(sz.data)

    @detail_route(methods=['post', 'get', 'delete'],
                  permission_classes=[IsAuthorOfAppointment],
                  filter_backends=[AppointmentUserFilter,
                                   AppointmentBookedFilter])
    def reminders(self, request, pk=None):
        """
        Endpoints for retrieve, create, update or delete reminder
        about appointment \n
        time_type: minutes, hours, days, weeks


        On GET request will returned list of reminders for concrete appointment
        (defaults reminders and one custom reminder if exists)
        """
        appointment = self.get_object()

        if request.method == 'GET':
            return self.get_reminders(appointment)

        reminder = getattr(appointment, 'reminder', None)

        if request.method == 'DELETE':
            try:
                reminder.delete()
            except AttributeError:
                raise NotFound
            return Response(status=status.HTTP_204_NO_CONTENT)

        data = request.data.copy()
        data.update({'appointment': appointment.pk})
        sz = self.get_serializer(reminder, data=data)
        sz.is_valid(raise_exception=True)
        sz.save()

        return Response(sz.data)

    @staticmethod
    def get_reminders(appointment: Appointment):
        reminders = set(ReminderTime.objects.filter(is_default=True))

        chosen_reminder = getattr(getattr(appointment, 'reminder', None),
                                  'reminder_time', None)
        if chosen_reminder is not None:
            chosen_reminder.is_chosen = True
            try:
                reminders.remove(chosen_reminder)
            except KeyError:
                pass
            reminders.add(chosen_reminder)

        sz = ReminderTimeSerializer(
            sorted(reminders, key=lambda x: (x.is_default, x.id)), many=True
        )
        return Response(sz.data)


class AppointmentClinicEventViewSet(MultiSerializerViewSetMixin,
                                    GenericViewSet):
    queryset = AppointmentClinicEvent.objects.all()
    permission_classes = (
        IsClinicsAdmin,
    )
    serializer_class = AppointmentClinicEventSerializer
    custom_serializer_classes = {
        'reject': serializers.Serializer,
        'suggest': AppointmentClinicWithSuggestionsSerializer,
        'reject_suggestions': serializers.Serializer,
    }
    filter_backends = (AppointmentClinicEventFilter,)

    @detail_route(methods=['post', ])
    def reject(self, request, **kwargs):
        """
        Endpoint for reject appointment by clinic admin.
        """
        event = self.get_object()
        AppointmentActions(
            event.appointment,
            SupportAdminTime().is_support_admin_time
        ).reject(event)
        return Response(AppointmentClinicEventSerializer(event).data)

    @detail_route(methods=['post', ])
    def accept(self, request, **kwargs):
        """
        Endpoint for accept appointment.

        If appointment open and event for current clinic is active,
        appointment will be reserved by this clinic.
        """
        event = self.get_object()
        sz = self.get_serializer(event, data=request.data)
        sz.is_valid(raise_exception=True)
        sz.save()
        AppointmentActions(
            event.appointment,
            SupportAdminTime().is_support_admin_time
        ).accept(event)
        check_status_appointment_after_reserved.apply_async(
            args=(event.appointment.id, ),
            countdown=settings.CHECK_APPOINTMENT_EXPIRED_AFTER_RESERVED)
        return Response(sz.data)

    @detail_route(methods=['post', ])
    def suggest(self, request, **kwargs):
        """
        Endpoint for add suggestions for appointment.

        If clinic admin want to change date and/or time
        for appointment he can add suggestions (minimum 3)\n
        For example,

            POST /api/v1/appointments/events/{id}/suggest

                {
                  "suggestions": [
                    {
                       "date": "2017-6-7",
                       "time": "10:00",
                       "doctor": 12,
                       "adjust_30_min": true
                    },
                    {
                       "date": "2017-6-8",
                       "time": "10:00",
                       "doctor": 12
                    },
                    {
                       "date": "2017-6-7",
                       "time": "14:00",
                       "doctor": 12
                    }
                  ]
                }

        """
        event = self.get_object()
        sz = self.get_serializer(event, data=request.data)
        sz.is_valid(raise_exception=True)
        with atomic():
            sz.save()
            AppointmentActions(
                event.appointment,
                SupportAdminTime().is_support_admin_time
            ).suggest(event)
        check_status_appointment_after_suggest.apply_async(
            args=(event.appointment.id,),
            countdown=settings.CHECK_APPOINTMENT_EXPIRED_AFTER_SUGGEST)
        return Response(sz.data)

    @detail_route(methods=['post'], permission_classes=[IsAuthorOfAppointment])
    def reject_suggestions(self, request, **kwargs):
        """
        Endpoint for reject admin's suggestions by user.

        If user no want to take any suggestions from
        clinic admin, he can just reject their.
        """
        event = self.get_object()
        AppointmentActions(
            event.appointment,
            SupportAdminTime().is_support_admin_time
        ).reject_suggestions(event)
        return Response(AppointmentClinicEventSerializer(event).data)

    @detail_route(methods=['post'], permission_classes=[IsAuthorOfAppointment],
                  url_path='accept_suggestion/(?P<suggestion_id>[0-9]+)',
                  serializer_class=serializers.Serializer)
    def accept_suggestion(self, request, pk=None, suggestion_id=None):
        """
        Endpoint for accept one of admin's suggestions.

        If user accept one of suggestion, an appointment
        will be reserved by this clinic
        """
        event = self.get_object()
        suggestion = get_object_or_404(
            AppointmentSuggestion.objects.all(), pk=suggestion_id)
        aa = AppointmentActions(
            event.appointment,
            SupportAdminTime().is_support_admin_time
        )
        aa.accept_suggestion(event, suggestion)
        sz = AppointmentClinicEventSerializer(self.get_object())
        check_status_appointment_after_reserved.apply_async(
            args=(event.appointment.id, ),
            countdown=settings.CHECK_APPOINTMENT_EXPIRED_AFTER_RESERVED)
        return Response(sz.data)


class AppointmentScheduleViewSet(GenericViewSet, mixins.ListModelMixin):
    """
    List appointment schedules with doctors

    For filtering by date, use

        GET /api/v1/appointments/schedules?
        appointment_starts=2017-1-1&appointment_ends=2017-12-31
    """
    queryset = AppointmentSchedule.objects.all().order_by('-id')
    serializer_class = AppointmentScheduleSerializer
    permission_classes = (
        Or(IsSuperAdmin, IsClinicsAdmin, IsDoctor),
    )
    filter_backends = (AppointmentScheduleFilter, DjangoFilterBackend, )
    filter_class = AppointmentScheduleDateTimeFilter
    pagination_class = ViewPagination


class ReminderDefaultTimeViewSet(ModelViewSet):
    """
    Endpoints for add/change/delete defaults reminder time for appointment
    """
    queryset = ReminderTime.objects.filter(is_default=True)
    permission_classes = (IsSuperAdmin, )
    serializer_class = ReminderTimeSerializer


class AppointmentRatingViewSet(GenericViewSet, mixins.ListModelMixin):
    """
    List ratings for clinic admin and super admins
    """
    queryset = AppointmentRating.objects.all().order_by('-id')
    serializer_class = AppointmentRatingSerializer
    permission_classes = (Or(IsSuperAdmin, IsClinicsAdmin),)
    filter_backends = (AppointmentRatingUserFilter,)
    pagination_class = ViewPagination
