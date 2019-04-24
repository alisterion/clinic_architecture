from clinicapp.pkg.common.choices import ChoiceEnum, ChoiceStringEnum


class AppointmentState(ChoiceEnum):
    Opened = 10
    WaitingForUserDecide = 20  # If clinic suggested
    UserRejectSuggestions = 30
    Reserved = 40
    TimeOut = 50  # None of clinics accepted or suggested appointment
    Confirmed = 60
    Canceled = 70


class AppointmentClinicState(ChoiceEnum):
    Active = 10
    Accepted = 20
    Suggested = 30
    Rejected = 40
    Inactive = 50
    RejectedSuggestions = 60


class ReminderTimeType(ChoiceStringEnum):
    Minutes = 'minutes'
    Hours = 'hours'
    Days = 'days'
    Weeks = 'weeks'
