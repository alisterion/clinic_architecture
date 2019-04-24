from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import ObjectDoesNotExist
from django.db.transaction import atomic
from django.utils.timezone import now as tz_now
from drf_extra_fields.relations import PresentablePrimaryKeyRelatedField
from drf_extra_fields.fields import DateTimeRangeField
from rest_framework import serializers
from rest_framework.exceptions import NotAuthenticated

from clinicapp.celery import app
from clinicapp.pkg.appointments.choices import (
    AppointmentState, AppointmentClinicState, ReminderTimeType
)
from clinicapp.pkg.appointments.models import (
    Appointment, AppointmentClinicEvent, AppointmentSuggestion,
    AppointmentSchedule, AppointmentReminder, AppointmentRating, ReminderTime
)
from clinicapp.pkg.appointments.settings import SUGGESTIONS_MIN_NUMBER
from clinicapp.pkg.appointments.utils import run_task_for_reminder_in_saving
from clinicapp.pkg.clinics.models import Clinic
from clinicapp.pkg.common.fields import GeoPointField, StatusField
from clinicapp.pkg.common.mixins import (
    SaveGeoPointMixin, StatusMixin, SaveDateTimeMixin
)
from clinicapp.pkg.users.choices import GroupType
from clinicapp.pkg.users.serializers import UserInfoSerializer
from clinicapp.pkg.users.models import Basket
from clinicapp.pkg.clinics.serializers import (
    DoctorSerializer, TreatmentSerializer
)

User = get_user_model()


class ClinicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clinic
        fields = ('id', 'name', 'address', 'phone', 'photo', )


class AutomaticSuggestionsSerializer(serializers.Serializer):
    date = serializers.DateField()
    time = serializers.TimeField()


class AppointmentSerializer(StatusMixin, SaveDateTimeMixin, SaveGeoPointMixin,
                            serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = ('id', 'patient', 'longitude', 'latitude', 'status',
                  'location', 'date', 'time', 'doctor', 'adjust_30_min',
                  'treatments', 'clinic', )
        read_only_fields = ('patient', 'longitude', 'latitude', 'status',
                            'doctor', 'adjust_30_min', 'treatments', 'clinic')

    point_field = 'location'
    date_time_field = 'date_time'

    status = StatusField(AppointmentState)
    location = GeoPointField()
    patient = UserInfoSerializer(read_only=True)
    treatments = TreatmentSerializer(many=True, read_only=True)
    clinic = serializers.SerializerMethodField()

    def get_clinic(self, obj):
        clinic = obj.get_clinic()
        return ClinicSerializer(clinic).data

    def validate_date(self, value):
        if value < tz_now().date():
            raise serializers.ValidationError("You can't choose past date")
        return value

    def _validate_basket(self):
        try:
            self.basket = (
                Basket.objects
                .by_user(self.context.get('request').user)
                .checkout().latest('date_created')
            )
        except ObjectDoesNotExist:
            self.basket = None
        if not self.basket and not self.instance:
            raise serializers.ValidationError("Basket is empty")

    @staticmethod
    def _validate_date_and_time(date, time):
        now = tz_now()
        if date == now.date() and time < now.time():
            raise serializers.ValidationError(
                {'time': "You can't choose past time"}
            )

    def _get_treatments(self):
        treatments = None

        if self.basket:
            treatments = self.basket.treatments.all()

        if self.instance:
            try:
                treatments = self.instance.treatments.all()
            except (TypeError, ValueError, AttributeError):
                pass
        if not treatments:
            raise serializers.ValidationError("Basket is empty")
        return treatments

    def _get_location(self, *, latitude, longitude):
        if self.instance:
            try:
                latitude = self.instance.location.get_y()
            except (TypeError, ValueError, AttributeError):
                pass
            try:
                longitude = self.instance.location.get_x()
            except (TypeError, ValueError, AttributeError):
                pass
        return latitude, longitude

    def _validate_user(self):
        user = getattr(self.context.get('request'), 'user', None)
        if not user:
            raise NotAuthenticated
        if not user.has_full_info():
            raise serializers.ValidationError(
                {'detail': 'Please fill out the profile'}
            )

    def validate(self, attrs):
        from clinicapp.pkg.appointments.actions import \
            AppointmentClinicSearcher

        self._validate_user()
        self._validate_date_and_time(attrs.get('date'), attrs.get('time'))
        self._validate_basket()

        treatments = self._get_treatments()

        latitude, longitude = self._get_location(
            latitude=attrs.get('latitude'),
            longitude=attrs.get('longitude')
        )

        self.clinic_searcher = AppointmentClinicSearcher(
            treatments, longitude, latitude, self.instance)
        return attrs

    @atomic()
    def create(self, validated_data):
        validated_data.update({
            'patient': self.context.get('request').user,
            'basket': self.basket
            # 'treatments': self.basket.treatments.all()
        })
        self.basket.set_status_booked()
        return super(AppointmentSerializer, self).create(validated_data)


class AppointmentAutomaticSuggestionsSerializer(AppointmentSerializer):
    class Meta(AppointmentSerializer.Meta):
        fields = AppointmentSerializer.Meta.fields + ('suggestions', )
        read_only_fields = AppointmentSerializer.Meta.read_only_fields +\
            ('suggestions', )

    suggestions = AutomaticSuggestionsSerializer(many=True)


class AppointmentClinicEventSerializer(
        StatusMixin, serializers.ModelSerializer):
    class Meta:
        model = AppointmentClinicEvent
        fields = ('id', 'appointment', 'clinic', 'status',
                  'doctor', 'adjust_30_min', 'treatments', )
        read_only_fields = ('appointment', 'clinic', 'status',
                            'treatments'
                            )

    status = StatusField(AppointmentClinicState)
    appointment = AppointmentSerializer(read_only=True)
    doctor = serializers.PrimaryKeyRelatedField(
        required=True, write_only=True,
        queryset=User.objects.filter(groups__name=GroupType.Doctor.value)
    )
    clinic = ClinicSerializer(read_only=True)
    treatments = TreatmentSerializer(
        source='appointment.treatments', many=True, read_only=True)
    adjust_30_min = serializers.BooleanField(
        required=False, write_only=True)

    def validate_doctor(self, value):
        if value.doctor.clinic_id != self.instance.clinic_id:
            raise serializers.ValidationError(
                "You can not add doctor from another clinic"
            )
        return value

    def update(self, instance, validated_data):
        doctor = validated_data.pop('doctor', None)
        adjust_30_min = validated_data.pop('adjust_30_min', False)
        appointment = instance.appointment
        appointment.adjust_30_min = adjust_30_min
        if doctor:
            appointment.doctor = doctor
        appointment.save(update_fields=['adjust_30_min', 'doctor'])
        return instance


class AppointmentSuggestionSerializer(SaveDateTimeMixin,
                                      serializers.ModelSerializer):
    class Meta:
        model = AppointmentSuggestion
        fields = ('id', 'date', 'time', 'doctor', 'adjust_30_min', 'date_time')

    date_time_field = 'date_time'
    date_time = serializers.DateTimeField(read_only=True)


class AppointmentClinicWithSuggestionsSerializer(
        StatusMixin, serializers.ModelSerializer):

    class Meta:
        model = AppointmentClinicEvent
        fields = ('id', 'appointment', 'clinic', 'status', 'suggestions', )
        read_only_fields = ('appointment', 'clinic', 'status', )

    status = StatusField(AppointmentClinicState)
    suggestions = AppointmentSuggestionSerializer(many=True)
    appointment = AppointmentSerializer(read_only=True)
    clinic = ClinicSerializer(read_only=True)

    def validate_suggestions(self, value):
        if len(value) < SUGGESTIONS_MIN_NUMBER:
            raise serializers.ValidationError(
                "You need add minimum %d suggestions"
                % SUGGESTIONS_MIN_NUMBER
            )
        # checking the unique of each suggestion
        if len(set(map(lambda x: tuple(x.values()), value))) != len(value):
            raise serializers.ValidationError(
                "Suggestions are must be different"
            )
        return value

    def update(self, instance, validated_data):
        suggestions = []
        for data in validated_data.pop('suggestions', []):
            suggestions.append(
                AppointmentSuggestion(appointment_event=instance, **data)
            )
        AppointmentSuggestion.objects.bulk_create(suggestions)
        return instance


class AppointmentScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppointmentSchedule
        fields = ('appointment', 'doctor', 'duration', 'adjust_30_min', )

    doctor = DoctorSerializer()
    adjust_30_min = serializers.SerializerMethodField()
    appointment = AppointmentSerializer()
    duration = DateTimeRangeField()

    def get_adjust_30_min(self, obj):
        return obj.appointment.adjust_30_min


class ReminderTimeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReminderTime
        fields = ('id', 'duration', 'time_type', 'is_default', 'is_chosen', )

    time_type = serializers.ChoiceField(ReminderTimeType.choices(),
                                        required=True)
    duration = serializers.IntegerField(min_value=1)
    is_chosen = serializers.SerializerMethodField()

    def get_is_chosen(self, obj):
        return getattr(obj, 'is_chosen', None)

    def validate(self, attrs):
        time_type = attrs.get('time_type')
        duration = attrs.get('duration')
        try:
            delta = timedelta(**{time_type: duration})
        except (TypeError, ValueError, OverflowError):
            raise serializers.ValidationError(
                {'time_type': 'Bad value',
                 'duration': 'It must be small integer'}
            )
        attrs.update({'before': delta})
        return attrs

    def save(self, **kwargs):
        # it will saving if only super admin add new ReminderType
        kwargs.setdefault('is_default', True)
        return super(ReminderTimeSerializer, self).save(**kwargs)


class AppointmentReminderBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppointmentReminder
        fields = ('id', 'reminder_time', )

    reminder_time = ReminderTimeSerializer(read_only=True)


class AppointmentReminderSerializer(AppointmentReminderBaseSerializer):
    class Meta:
        model = AppointmentReminder
        fields = ('id', 'appointment', 'reminder_time', 'reminder_time_id',
                  'duration', 'time_type', )

    appointment = serializers.PrimaryKeyRelatedField(
        queryset=Appointment.objects.all(), required=False
    )

    time_type = serializers.ChoiceField(ReminderTimeType.choices(),
                                        required=False, write_only=True)
    duration = serializers.IntegerField(required=False, write_only=True,
                                        min_value=1)

    reminder_time_id = serializers.PrimaryKeyRelatedField(
        queryset=ReminderTime.objects.filter(is_default=True),
        required=False, write_only=True
    )

    @staticmethod
    def _validate_time_parameters(reminder_time: ReminderTime,
                                  duration: int, time_type: str):
        if not reminder_time and not (duration or time_type):
            msg = "One of two options: reminder_time_id or " \
                  "(duration and time_type) -  is required"
            raise serializers.ValidationError(
                {'reminder_time_id': msg, 'duration': msg, 'time_type': msg}
            )
        if reminder_time and (duration or time_type):
            msg = "Only one of two options: reminder_time_id or " \
                  "(duration and time_type) -  is required"
            raise serializers.ValidationError(
                {'reminder_time_id': msg, 'duration': msg, 'time_type': msg}
            )

    @staticmethod
    def _get_reminder_timedelta(reminder_time: ReminderTime,
                                duration: int, time_type: str):
        if reminder_time:
            before = reminder_time.before
        else:
            try:
                before = timedelta(**{time_type: duration})
            except (TypeError, ValueError, OverflowError):
                raise serializers.ValidationError({
                    'time_type': 'Bad value', 'duration': 'It must be integer'
                })
        return before

    @staticmethod
    def _validate_time_of_run_reminder(
            reminder_timedelta: timedelta, appointment: Appointment):
        if tz_now() + reminder_timedelta > appointment.date_time:
            raise serializers.ValidationError({
                'duration': "You can't add reminder in the past"
            })

    def validate(self, attrs):
        appointment = getattr(self.instance, 'appointment',
                              attrs.get('appointment'))
        reminder_time = attrs.get('reminder_time_id')
        duration = attrs.get('duration')
        time_type = attrs.get('time_type')

        self._validate_time_parameters(reminder_time, duration, time_type)
        reminder_timedelta = self._get_reminder_timedelta(
            reminder_time, duration, time_type)

        self._validate_time_of_run_reminder(reminder_timedelta, appointment)
        return attrs

    def _its_custom_old_reminder(self):
        return self.instance and self.instance.reminder_time and not \
                    self.instance.reminder_time.is_default

    def _get_reminder_time(self, ):
        if self.validated_data.get('reminder_time_id'):
            reminder_time = self.validated_data.pop('reminder_time_id')
            if self._its_custom_old_reminder():
                self.instance.reminder_time.delete()
        else:
            duration = self.validated_data.pop('duration')
            time_type = self.validated_data.pop('time_type')

            if self._its_custom_old_reminder():
                reminder_time = self.instance.reminder_time
                reminder_time.duration = duration
                reminder_time.time_type = time_type
                reminder_time.save()
            else:
                reminder_time = ReminderTime.objects.create(
                    duration=duration, time_type=time_type
                )
        return reminder_time

    def _process_validate_data_with_reminder_time(self):
        reminder_time = self._get_reminder_time()
        self.validated_data.update({
            'reminder_time': reminder_time
        })

    @atomic()
    def save(self, **kwargs):
        self._process_validate_data_with_reminder_time()
        self.validated_data.update({'already_send': False})

        if hasattr(self.instance, 'task_id'):
            # cancel pending task for send reminder
            # if user change reminder time
            app.control.revoke(task_id=self.instance.task_id, terminate=True)

        instance = super(AppointmentReminderSerializer, self).save(**kwargs)

        run_task_for_reminder_in_saving(instance)
        return instance


class AppointmentRatingBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppointmentRating
        fields = ('id', 'rate', 'comment', )


class AppointmentRatingSerializer(AppointmentRatingBaseSerializer):
    class Meta:
        model = AppointmentRating
        fields = ('id', 'appointment', 'rate', 'comment', )

    rate = serializers.IntegerField(min_value=1, max_value=5)
    appointment = PresentablePrimaryKeyRelatedField(
        presentation_serializer=AppointmentSerializer,
        queryset=Appointment.objects.all(),
    )


class AppointmentHistorySerializer(AppointmentSerializer):
    treatments = TreatmentSerializer(many=True)
    location = serializers.SerializerMethodField()

    def get_location(self, obj: Appointment):
        clinic_location = getattr(obj.get_clinic(), 'location', None)
        return GeoPointField().to_representation(clinic_location)


class AppointmentPassedHistorySerializer(AppointmentHistorySerializer):
    class Meta(AppointmentHistorySerializer.Meta):
        fields = AppointmentHistorySerializer.Meta.fields + ('rating', )

    rating = AppointmentRatingBaseSerializer()


class AppointmentUpcomingHistorySerializer(AppointmentHistorySerializer):
    class Meta(AppointmentHistorySerializer.Meta):
        fields = AppointmentHistorySerializer.Meta.fields + ('reminder', )

    reminder = AppointmentReminderBaseSerializer()
