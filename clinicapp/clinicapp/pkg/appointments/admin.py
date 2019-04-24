from django.contrib import admin

from clinicapp.pkg.appointments.models import Appointment,\
    AppointmentClinicEvent, AppointmentSuggestion, ReminderTime, \
    AppointmentReminder, AppointmentRating, AppointmentSchedule

admin.site.register(Appointment)
admin.site.register(AppointmentClinicEvent)
admin.site.register(AppointmentSuggestion)
admin.site.register(AppointmentSchedule)
admin.site.register(ReminderTime)
admin.site.register(AppointmentReminder)
admin.site.register(AppointmentRating)
