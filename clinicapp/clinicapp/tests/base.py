import os

from django.conf import settings
from django.contrib.auth import get_user_model

from clinicapp.pkg.clinics.models import Clinic
from clinicapp.pkg.diagnoses.models import PhotoAnswer, PhotoQuestion

User = get_user_model()


class UploadedFilesCleanerMixin(object):
    @property
    def images(self):
        """
        :return GeneratorTypes:
        """
        for img in Clinic.objects.only('photo'):
            yield img.photo
        for img in PhotoQuestion.objects.only('example'):
            yield img.example
        for img in PhotoAnswer.objects.only('image'):
            yield img.image
        for img in User.objects.only('photo'):
            yield img.photo

    @staticmethod
    def _cleanup_uploaded_image_path(image_path):
        """
        """
        upload_dir = os.path.dirname(image_path)
        media_root = settings.MEDIA_ROOT
        if not media_root:
            return

        while upload_dir.startswith(media_root):
            try:
                os.rmdir(upload_dir)
                upload_dir = os.path.dirname(upload_dir)
            except (IOError, OSError):
                break

    def _clean_up_uploaded_images(self):
        """

        """
        for img in self.images:
            try:
                image_path = img.path
                img.delete()
                self._cleanup_uploaded_image_path(image_path)
            except ValueError:
                pass

    def tearDown(self):
        """

        """
        self._clean_up_uploaded_images()
        super(UploadedFilesCleanerMixin, self).tearDown()
