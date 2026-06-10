from app.plugins import PluginBase, Menu, MountPoint
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _

from .api import TaskFindGCPDetect, TaskFindGCPCheck, TaskFindGCPDownload


class Plugin(PluginBase):
    def main_menu(self):
        return [Menu(_("Find-GCP"), self.public_url(""), "fa fa-map-marker-alt fa-fw")]

    def app_mount_points(self):
        @login_required
        def index(request):
            return render(request, self.template_path("app.html"), {
                'title': 'Find-GCP',
            })

        return [
            MountPoint('$', index),
        ]

    def api_mount_points(self):
        return [
            MountPoint('task/(?P<pk>[^/.]+)/detect', TaskFindGCPDetect.as_view()),
            MountPoint('task/[^/.]+/check/(?P<celery_task_id>.+)', TaskFindGCPCheck.as_view()),
            MountPoint('task/[^/.]+/download/(?P<celery_task_id>.+)', TaskFindGCPDownload.as_view()),
        ]
