from app.plugins import PluginBase, Menu, MountPoint
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _

from .api import TaskFindGCPDetect, TaskFindGCPCheck


class Plugin(PluginBase):
    def main_menu(self):
        return [Menu(_("Find-GCP"), self.public_url(""), "fa fa-map-marker-alt fa-fw")]

    def include_js_files(self):
        # Loaded into the dashboard; registers the "Find-GCP task" button that
        # runs the single-pass workflow (see public/load_buttons.js).
        return ['load_buttons.js']

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
            MountPoint('task/(?P<pk>[^/.]+)/check/(?P<celery_task_id>.+)', TaskFindGCPCheck.as_view()),
        ]
