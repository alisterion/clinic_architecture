import urllib

from django.contrib.auth import get_user_model
from django.core.urlresolvers import reverse
from model_mommy.recipe import Recipe

from clinicapp.pkg.appointments.models import (
    Appointment,
    AppointmentClinicEvent,
    AppointmentSchedule,
    AppointmentReminder,
    AppointmentRating,
    ReminderTime,
)
from clinicapp.pkg.clinics.models import (
    Clinic,
    Doctor,
    Schedule,
    Service,
    Treatment,
    RadiusSearch,
    TreatmentLearnMore
)
from clinicapp.pkg.diagnoses.models import (
    Diagnose,
    Question,
    Answer,
    PhotoQuestion,
    PhotoAnswer,
    QuestionChoice,
    QuestionCategory
)
from clinicapp.pkg.users.models import UserLocations, Basket, UserUUID
from clinicapp.pkg.common.models import FAQ, ContactUsCategory, \
    ContactUsMessage, FAQCategory
from clinicapp.pkg.notifications.models import UserNotification


def build_url(*args, **kwargs):
    get = kwargs.pop('get', {})
    url = reverse(*args, **kwargs)
    if get:
        url += '?' + urllib.parse.urlencode(get)
    return url


User = get_user_model()

ClinicRecipe = Recipe(Clinic)
DoctorRecipe = Recipe(Doctor)
TreatmentRecipe = Recipe(Treatment)
TreatmentLearnMoreRecipe = Recipe(TreatmentLearnMore)
ServiceRecipe = Recipe(Service)
ScheduleRecipe = Recipe(Schedule)
UserRecipe = Recipe(User, is_active=True, photo='1.jpg', _fill_optional=True)
DiagnoseRecipe = Recipe(Diagnose)
QuestionRecipe = Recipe(Question)
ChoiceRecipe = Recipe(QuestionChoice)
PhotoQuestionRecipe = Recipe(PhotoQuestion)
PhotoAnswerRecipe = Recipe(PhotoAnswer)
AnswerRecipe = Recipe(Answer)
RadiusRecipe = Recipe(RadiusSearch)
AppointmentRecipe = Recipe(Appointment, _fill_optional=['basket'])
AppointmentScheduleRecipe = Recipe(AppointmentSchedule)
AppointmentEventRecipe = Recipe(AppointmentClinicEvent)
AppointmentReminderRecipe = Recipe(AppointmentReminder)
ReminderTimeRecipe = Recipe(ReminderTime)
AppointmentRatingRecipe = Recipe(AppointmentRating)
FAQRecipe = Recipe(FAQ)
FAQCategoryRecipe = Recipe(FAQCategory)
ContactUsCategoryRecipe = Recipe(ContactUsCategory)
ContactUsMessageRecipe = Recipe(ContactUsMessage)
UserNotificationRecipe = Recipe(UserNotification)
UserLocationsRecipe = Recipe(UserLocations)
BasketRecipe = Recipe(Basket)
UserUUIDRecipe = Recipe(UserUUID)
CategoryRecipe = Recipe(QuestionCategory)
