from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hypha.apply.users.roles import (
    COMMUNITY_REVIEWER_GROUP_NAME,
    REVIEWER_GROUP_NAME,
    STAFF_GROUP_NAME,
)

REVIEW_GROUPS = [
    STAFF_GROUP_NAME,
    REVIEWER_GROUP_NAME,
    COMMUNITY_REVIEWER_GROUP_NAME,
]
LIMIT_TO_STAFF = {"groups__name": STAFF_GROUP_NAME, "is_active": True}
LIMIT_TO_REVIEWERS = {"groups__name": REVIEWER_GROUP_NAME, "is_active": True}
LIMIT_TO_COMMUNITY_REVIEWERS = {
    "groups__name": COMMUNITY_REVIEWER_GROUP_NAME,
    "is_active": True,
}
LIMIT_TO_REVIEWER_GROUPS = {"groups__name__in": REVIEW_GROUPS, "is_active": True}


# Managing async submission exports

STATUS_ERROR = "error"
STATUS_SUCCESS = "success"
STATUS_GENERATING = "generating"

STATUS_CHOICES = [
    (STATUS_ERROR, _("Failed")),
    (STATUS_SUCCESS, _("Success")),
    (STATUS_GENERATING, _("In Progress")),
]


class SubmissionPDFExportManager(models.Model):
    """
    Like Hypha's SubmissionExportManager but for PDF exports instead of CSV
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        limit_choices_to=LIMIT_TO_STAFF,
        on_delete=models.CASCADE,
    )

    export_data = models.BinaryField()

    created_time = models.DateTimeField(auto_now_add=True)

    completed_time = models.DateTimeField(null=True)

    status = models.CharField(choices=STATUS_CHOICES, default=STATUS_GENERATING)

    total_export = models.IntegerField(null=True)

    def set_completed_and_save(self) -> None:
        """Sets the status to completed and saves the object"""
        self.status = "success"
        self.completed_time = timezone.now()
        self.save()

    def set_failed_and_save(self) -> None:
        """Sets the status to error and saves the object"""
        self.status = "error"
        self.save()

    def get_absolute_url(self) -> str:
        """Returns the submissions all page where the user can download the file

        Primarily used for tasks
        """
        return reverse("apply:submissions:list")
