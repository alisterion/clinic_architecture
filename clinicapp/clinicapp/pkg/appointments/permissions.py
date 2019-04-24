from rest_framework.permissions import BasePermission

from clinicapp.pkg.appointments.models import Appointment


class IsAuthorOfAppointment(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, Appointment):
            return obj.patient == request.user
        return obj.appointment.patient == request.user
