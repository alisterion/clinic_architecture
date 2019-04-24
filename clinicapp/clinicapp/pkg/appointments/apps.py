from django.apps import AppConfig


class AppointmentsConfig(AppConfig):
    name = 'clinicapp.pkg.appointments'

    def ready(self):
        import clinicapp.pkg.appointments.signal_handlers
