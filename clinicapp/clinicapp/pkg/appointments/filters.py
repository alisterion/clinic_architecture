from django.contrib.auth import get_user_model
from django.contrib.gis.measure import D
from django.db.models import Count, QuerySet
from django.utils.timezone import now as tz_now
import django_filters

from rest_framework.exceptions import ValidationError
from rest_framework.filters import BaseFilterBackend

from clinicapp.pkg.appointments.choices import AppointmentClinicState, \
    AppointmentState
from clinicapp.pkg.appointments.models import AppointmentSchedule
from clinicapp.pkg.appointments.settings import NO_CLINIC_MSG
from clinicapp.pkg.clinics.models import RadiusSearch
from clinicapp.pkg.common.services.online import OnlineService
from clinicapp.pkg.users.services.user_service import GroupService

User = get_user_model()


def filter_by_treatments(queryset, searcher):
    """
    Filter for Clinic QuerySet by treatments
    :param queryset: Clinic QuerySet
    :param searcher: actions.AppointmentClinicSearcher
    :return: Clinic QuerySet
    """
    queryset = queryset.filter(
        treatments__in=searcher.get_treatments()
    ).annotate(cnt=Count('treatments')).filter(
        cnt=searcher.get_treatments().count()
    )

    if searcher.raise_exception and queryset.count() == 0:
        raise ValidationError(
            {'treatments': NO_CLINIC_MSG.format(field='treatments')})
    return queryset


def filter_by_location(queryset, searcher=None, point=None,
                       raise_exception=True):
    """
    Filter for Clinic QuerySet by location
    :param queryset: Clinic QuerySet
    :param searcher: action.AppointmentClinicSearcher
    :param point: Point
    :param raise_exception: bool
    :return: Clinic QuerySet
    """
    point = point or searcher.get_geo_point()
    radius = RadiusSearch.get_radius_value_for_appointment()
    if point:
        queryset = queryset.filter(
            location__distance_lte=(point, D(km=radius))
        )

    if raise_exception and queryset.count() == 0:
        raise ValidationError(
            {'location': NO_CLINIC_MSG.format(field='location')})
    return queryset


def filter_clinics_which_reject(queryset, searcher):
    """
    Filter for Clinic QuerySet by existing rejected events
    :param queryset: Clinic QuerySet
    :param searcher: action.AppointmentClinicSearcher
    :return: Clinic QuerySet
    """
    appointment = searcher.get_appointment()
    if not appointment:
        return queryset
    queryset = queryset.exclude(
        appointment_events__in=appointment.events.all(),
        appointment_events__status=AppointmentClinicState.Rejected.value
    )
    if searcher.raise_exception and queryset.count() == 0:
        msg = NO_CLINIC_MSG.format(field='location and treatments')
        raise ValidationError({
            'location': msg, 'treatments': msg
        })
    return queryset


def filter_clinics_which_suggested(queryset, searcher):
    """
    Filter for Clinic QuerySet by existing suggested
    (and then rejected by user) events
    :param queryset: Clinic QuerySet
    :param searcher: action.AppointmentClinicSearcher
    :return: Clinic QuerySet
    """
    appointment = searcher.get_appointment()
    if not appointment:
        return queryset
    queryset = queryset.exclude(
        appointment_events__in=appointment.events.all(),
        appointment_events__status=AppointmentClinicState.
        RejectedSuggestions.value
    )
    if searcher.raise_exception and queryset.count() == 0:
        msg = NO_CLINIC_MSG.format(field='location and treatments')
        raise ValidationError({
            'location': msg, 'treatments': msg
        })
    return queryset


def filter_clinics_online(queryset: QuerySet, searcher):
    """

    :param queryset: Clinic QuerySet
    :param searcher: AppointmentClinicSearcher
    :return: Clinic QuerySet
    """
    queryset = queryset.filter(
        admin__id__in=OnlineService.filter_online(User.objects.clinic_admins())
    )
    if searcher.raise_exception and queryset.count() == 0:
        msg = NO_CLINIC_MSG.format(field='location and treatments')
        raise ValidationError({
            'location': msg, 'treatments': msg
        })
    return queryset


class AppointmentUserFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        if GroupService.is_a_super_admin(request.user):
            return queryset
        if GroupService.is_a_clinic_admin(request.user):
            return queryset.filter(clinic__admin=request.user)
        return queryset.filter(patient=request.user)


class AppointmentUpcomingFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        return queryset.filter(date_time__gt=tz_now())


class AppointmentPassFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        return queryset.filter(date_time__lte=tz_now())


class AppointmentBookedFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        return queryset.filter(status=AppointmentState.Confirmed.value)


class AppointmentClinicEventFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        if GroupService.is_a_clinic_admin(request.user):
            return queryset.filter(clinic__admin=request.user)
        if GroupService.is_a_super_admin(request.user):
            return queryset
        return queryset.filter(appointment__patient=request.user)


class AppointmentScheduleFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        if GroupService.is_a_super_admin(request.user):
            return queryset.all()
        if GroupService.is_a_clinic_admin(request.user):
            return queryset.filter(doctor__doctor__clinic__admin=request.user)
        if GroupService.is_a_doctor(request.user):
            return queryset.filter(doctor=request.user)
        return queryset.none()


class AppointmentStatusRatingFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        return queryset.filter(
            status=AppointmentState.Confirmed.value, date_time__lt=tz_now()
        )


class AppointmentRatingUserFilter(BaseFilterBackend):
    def filter_queryset(self, request, queryset, view):
        if GroupService.is_a_super_admin(request.user):
            return queryset
        if GroupService.is_a_clinic_admin(request.user):
            return queryset.filter(appointment__clinic__admin=request.user)
        return queryset.filter(appointment__patient=request.user)


class AppointmentScheduleDateTimeFilter(django_filters.FilterSet):
    class Meta:
        model = AppointmentSchedule
        fields = ['appointment_starts', 'appointment_ends']
        strict = django_filters.STRICTNESS.IGNORE

    appointment_starts = django_filters.DateTimeFilter(
        'duration', lookup_expr='startswith__gte')
    appointment_ends = django_filters.DateTimeFilter(
        'duration', lookup_expr='endswith__lte')
