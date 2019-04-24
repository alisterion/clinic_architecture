from rest_framework import routers

from clinicapp.pkg.appointments.views import AppointmentViewSet, \
    AppointmentClinicEventViewSet, AppointmentScheduleViewSet, \
    ReminderDefaultTimeViewSet, AppointmentRatingViewSet

router = routers.SimpleRouter(trailing_slash=False)
router.register(r'appointments', AppointmentViewSet, 'appointment')
router.register(r'reminder/defaults', ReminderDefaultTimeViewSet, 'reminder')
router.register(r'appointments/events', AppointmentClinicEventViewSet,
                'appointment-event')
router.register(r'appointments/schedules', AppointmentScheduleViewSet,
                'appointment-schedule')
router.register(r'appointments/rating', AppointmentRatingViewSet,
                'appointment-rating')

urlpatterns = router.urls + []
